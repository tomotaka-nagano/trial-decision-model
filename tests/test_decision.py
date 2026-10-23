import json
from contextlib import contextmanager

import httpx2
import pytest
from exmgai.decision import DecisionResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import decision
from app.decision import ServiceError, build_questions
from app.main import app, get_executor
from app.schemas import DecisionInput


@pytest.fixture
def payload():
    return {
        'state': '新しい取引申請を審査してください。',
        'noul': {'enabled': True, 'instructions': '承認すべきですか？'},
        'choice': {'enabled': True, 'criteria': [
            {'key': 'manual', 'description': '手動審査'}, {'key': 'auto', 'description': '自動承認'},
        ]},
        'score': {'enabled': True, 'criteria': ['低リスク', '中リスク', '高リスク']},
    }


def test_valid_input(payload):
    assert DecisionInput.model_validate(payload).choice.criteria[0].key == 'manual'


@pytest.mark.parametrize('field', ['state', 'noul', 'choice', 'score'])
def test_empty_enabled_inputs_rejected(payload, field):
    payload[field] = ' ' if field == 'state' else {'enabled': True}
    with pytest.raises(ValidationError):
        DecisionInput.model_validate(payload)


def test_no_enabled_question_rejected():
    with pytest.raises(ValidationError):
        DecisionInput(state='質問')


def test_duplicate_keys_rejected(payload):
    payload['choice']['criteria'][1]['key'] = 'manual'
    with pytest.raises(ValidationError):
        DecisionInput.model_validate(payload)


def test_disabled_empty_inputs_accepted():
    request = DecisionInput(state='質問', noul={'enabled': True, 'instructions': '判断してください'})
    assert not request.choice.enabled


def test_limits_and_strict_types(payload):
    payload['state'] = 'x' * 20001
    with pytest.raises(ValidationError):
        DecisionInput.model_validate(payload)
    payload['state'] = '質問'
    payload['noul']['enabled'] = 'true'
    with pytest.raises(ValidationError):
        DecisionInput.model_validate(payload)


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def response():
    return DecisionResponse.model_validate({
        'model': 'Microsoft-Decision-1', 'usage': {'input_tokens': 123},
        'answers': {
            'approve': {'type': 'noul', 'noul': 0.8},
            'route': {'type': 'choice', 'choice': 'manual', 'confidence': 0.7,
                      'probabilities': {'manual': 0.7, 'auto': 0.3}},
            'risk': {'type': 'score', 'score': 1.2, 'confidence': 0.6,
                     'legend': {0: '低リスク', 1: '中リスク', 2: '高リスク'},
                     'probabilities': {0: 0.1, 1: 0.6, 2: 0.3}},
        },
    })


def test_sdk_conversion(payload):
    payload['choice']['instructions'] = '審査経路を選択'
    questions = build_questions(DecisionInput.model_validate(payload))
    assert questions['route'].criteria['manual'] == '手動審査'
    assert questions['route'].instructions == '審査経路を選択'
    assert questions['risk'].criteria == ['低リスク', '中リスク', '高リスク']


@pytest.mark.parametrize('enabled,question_id', [('noul', 'approve'), ('choice', 'route'), ('score', 'risk')])
def test_only_enabled_type_sent(payload, enabled, question_id):
    for kind in ('noul', 'choice', 'score'):
        payload[kind]['enabled'] = kind == enabled
    assert set(build_questions(DecisionInput.model_validate(payload))) == {question_id}


def test_normalization(payload, response):
    response._input_token_cost = 0.6
    result = decision.normalize(response, build_questions(DecisionInput.model_validate(payload)), True)
    assert result['answers']['risk']['legend']['1'] == '中リスク'
    assert result['answers']['approve']['noul'] == 0.8
    assert result['estimated_cost_usd'] == pytest.approx(0.0000738)
    assert decision.normalize(response, build_questions(DecisionInput.model_validate(payload)), False)[
        'estimated_cost_usd'] is None


def test_missing_answer_rejected(payload, response):
    response.answers.pop('risk')
    with pytest.raises(ServiceError, match='必要な項目'):
        decision.normalize(response, build_questions(DecisionInput.model_validate(payload)), True)


def test_api_success(client, payload, response):
    def run(request):
        return decision.normalize(response, build_questions(request), False)
    app.dependency_overrides[get_executor] = lambda: run
    result = client.post('/api/decision', json=payload)
    assert result.status_code == 200
    assert result.json()['input_tokens'] == 123


def test_validation_does_not_echo_input(client, payload):
    payload['state'] = 'SECRET' * 4000
    result = client.post('/api/decision', json=payload)
    assert result.status_code == 422
    assert 'SECRET' not in result.text


@pytest.mark.parametrize('status', [429, 502, 503, 504])
def test_safe_service_errors(client, payload, status):
    def fail(request):
        raise ServiceError(status, '安全なエラー')
    app.dependency_overrides[get_executor] = lambda: fail
    result = client.post('/api/decision', json=payload)
    assert result.status_code == status
    assert result.json()['detail'] == '安全なエラー'


def test_concurrency_limit(client, payload):
    for _ in range(4):
        app.state.slots.acquire()
    try:
        assert client.post('/api/decision', json=payload).status_code == 429
    finally:
        for _ in range(4):
            app.state.slots.release()


@pytest.mark.parametrize('error,status', [
    (httpx2.ReadTimeout('SECRET'), 504), (httpx2.ConnectError('SECRET'), 502),
    (FileNotFoundError('SECRET'), 503), (ValueError('SECRET'), 503),
])
def test_sdk_error_mapping(monkeypatch, payload, error, status):
    @contextmanager
    def fail():
        raise error
        yield
    monkeypatch.setattr(decision, 'configured_decision', fail)
    with pytest.raises(ServiceError) as caught:
        decision.execute(DecisionInput.model_validate(payload))
    assert caught.value.status == status
    assert 'SECRET' not in str(caught.value)


def test_health_and_safe_config(client):
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/api/config').json()['limits']['rows'] == 20
    assert client.get('/env.toml').status_code == 404


def test_reject_cross_origin_and_form_posts(client, payload):
    assert client.post('/api/decision', json=payload, headers={'Origin': 'https://other.test'}).status_code == 403
    assert client.post('/api/decision', data={'state': 'test'}).status_code == 415


def write_config(tmp_path, monkeypatch, auth='api_key', credential='azure_cli'):
    example = (decision.ROOT / 'env.toml.example').read_text(encoding='utf-8')
    example = example.replace('type = "api_key"', f'type = "{auth}"')
    example = example.replace('credential = "azure_cli"', f'credential = "{credential}"')
    (tmp_path / 'env.toml').write_text(example, encoding='utf-8')
    monkeypatch.setattr(decision, 'ROOT', tmp_path)


def mock_transport(monkeypatch, reply, status=200):
    clients, requests = [], []
    client_type = httpx2.Client
    def respond(request):
        requests.append(request)
        return httpx2.Response(status, json=reply)
    def create_client():
        client = client_type(transport=httpx2.MockTransport(respond))
        clients.append(client)
        return client
    monkeypatch.setattr(decision.httpx2, 'Client', create_client)
    return clients, requests


def test_full_sdk_http_roundtrip(tmp_path, monkeypatch, payload, response):
    write_config(tmp_path, monkeypatch)
    clients, requests = mock_transport(monkeypatch, response.model_dump(mode='json'))
    result = decision.execute(DecisionInput.model_validate(payload))
    assert result['answers']['risk']['score'] == 1.2
    assert requests[0].url.path == '/providers/microsoft/v1/systemone'
    assert requests[0].headers['api-key'] == 'your-api-key'
    sent = json.loads(requests[0].content)
    assert sent['state'] == payload['state']
    assert sent['questions']['route']['criteria']['manual'] == '手動審査'
    assert sent['model'] == 'your-microsoft-decision-1-deployment'
    assert clients[0].is_closed


@pytest.mark.parametrize('credential', ['azure_cli', 'default'])
def test_entra_authentication(tmp_path, monkeypatch, payload, response, credential):
    write_config(tmp_path, monkeypatch, auth='entra_id', credential=credential)
    clients, requests = mock_transport(monkeypatch, response.model_dump(mode='json'))
    used = []
    @contextmanager
    def fake_credential(**kwargs):
        used.append(credential)
        yield object()
    credential_type = 'AzureCliCredential' if credential == 'azure_cli' else 'DefaultAzureCredential'
    monkeypatch.setattr(decision, credential_type, fake_credential)
    monkeypatch.setattr(decision, 'get_bearer_token_provider', lambda *args: lambda: 'test-token')
    decision.execute(DecisionInput.model_validate(payload))
    assert requests[0].headers['Authorization'] == 'Bearer test-token'
    assert 'api-key' not in requests[0].headers
    assert used == [credential] and clients[0].is_closed


@pytest.mark.parametrize('status', [401, 403, 429, 500])
def test_upstream_http_errors_safe_and_closed(tmp_path, monkeypatch, payload, status):
    write_config(tmp_path, monkeypatch)
    clients, requests = mock_transport(monkeypatch, {'error': {'message': 'SECRET'}}, status)
    with pytest.raises(ServiceError) as caught:
        decision.execute(DecisionInput.model_validate(payload))
    assert caught.value.status == 502
    assert 'SECRET' not in str(caught.value)
    assert len(requests) == 1
    assert clients[0].is_closed


def test_static_assets_and_headers(client):
    assert client.get('/').status_code == 200
    for name in ('app.js', 'style.css', 'vendor/lucide.min.js'):
        response = client.get(f'/static/{name}')
        assert response.status_code == 200
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']