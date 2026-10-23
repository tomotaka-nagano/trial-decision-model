import json
import socket
from pathlib import Path
from threading import Event, Thread

import pytest
import uvicorn
from playwright.sync_api import expect

STORAGE_KEY = 'decision-workspace.question-sets.v1'
REPLY = {
    'model': 'Microsoft-Decision-1', 'input_tokens': 123, 'estimated_cost_usd': 0.0000738,
    'answers': {
        'approve': {'type': 'noul', 'noul': 0.8},
        'route': {'type': 'choice', 'choice': 'manual', 'confidence': 0.7,
                  'probabilities': {'manual': 0.7, 'auto': 0.3}},
        'risk': {'type': 'score', 'score': 1.2, 'confidence': 0.6,
                 'legend': {'0': '低リスク', '1': '中リスク', '2': '高リスク'},
                 'probabilities': {'0': 0.1, '1': 0.6, '2': 0.3}},
    },
}


class TestServer(uvicorn.Server):
    __test__ = False

    def __init__(self, config):
        super().__init__(config)
        self.ready = Event()

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        self.ready.set()


@pytest.fixture(scope='session')
def server_url():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        server = TestServer(uvicorn.Config('app.main:app', log_level='error'))
        thread = Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        assert server.ready.wait(15), 'Test server did not start'
        try:
            yield f'http://127.0.0.1:{sock.getsockname()[1]}'
        finally:
            server.should_exit = True
            thread.join(15)
            assert not thread.is_alive()


@pytest.fixture
def workspace(page, server_url):
    page.goto(server_url)
    expect(page.locator('.lucide').first).to_be_visible()
    expect(page.locator('#library-controls')).to_be_enabled()
    return page


def mock_decision(page, reply=REPLY):
    page.route('**/api/decision', lambda route: route.fulfill(json=reply))


@pytest.mark.parametrize('width,height', [(1440, 1000), (390, 844)])
def test_layout_and_results(workspace, width, height):
    workspace.set_viewport_size({'width': width, 'height': height})
    errors = []
    workspace.on('pageerror', lambda error: errors.append(str(error)))
    mock_decision(workspace)
    workspace.get_by_role('button', name='実行', exact=True).click()
    expect(workspace.locator('#status')).to_have_text('完了')
    expect(workspace.locator('#noul-result .metric-value')).to_have_text('80%')
    expect(workspace.locator('#choice-result .metric-value')).to_have_text('manual')
    expect(workspace.locator('#score-result .metric-value')).to_have_text('1.2')
    assert workspace.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not errors
    Path('test-results').mkdir(exist_ok=True)
    workspace.screenshot(path=f'test-results/workspace-{width}.png', full_page=True)


def test_disabled_questions_and_payload(workspace):
    requests = []
    workspace.route('**/api/decision', lambda route: (
        requests.append(route.request.post_data_json), route.fulfill(json=REPLY)))
    workspace.locator('#choice-enabled').uncheck()
    workspace.locator('#score-enabled').uncheck()
    expect(workspace.locator('#choice-instructions')).to_be_disabled()
    workspace.get_by_role('button', name='実行', exact=True).click()
    expect(workspace.locator('#status')).to_have_text('完了')
    assert requests[0]['choice']['criteria'] == []
    assert requests[0]['score']['criteria'] == []
    expect(workspace.locator('#choice-result')).to_contain_text('無効')


def test_busy_prevents_edits_and_double_submit(workspace):
    pending = []
    workspace.route('**/api/decision', lambda route: pending.append(route))
    workspace.get_by_role('button', name='実行', exact=True).click()
    expect(workspace.locator('#run')).to_be_disabled()
    expect(workspace.locator('#state')).to_be_disabled()
    expect(workspace.locator('#save')).to_be_disabled()
    expect(workspace.locator('#status')).to_have_text('実行中')
    assert len(pending) == 1
    pending[0].fulfill(json=REPLY)
    expect(workspace.locator('#run')).to_be_enabled()


def test_saved_question_restores_after_reload(workspace):
    workspace.locator('#state').fill('保存した質問本文')
    workspace.locator('#noul-instructions').fill('判断指示')
    workspace.locator('#score-enabled').uncheck()
    workspace.locator('#set-name').fill('審査セット')
    workspace.locator('#save').click()
    expect(workspace.locator('#notice')).to_have_text('質問を保存しました。')
    workspace.reload()
    workspace.locator('#saved-set').select_option(label='審査セット')
    workspace.locator('#restore').click()
    expect(workspace.locator('#state')).to_have_value('保存した質問本文')
    expect(workspace.locator('#noul-instructions')).to_have_value('判断指示')
    expect(workspace.locator('#score-enabled')).not_to_be_checked()
    expect(workspace.locator('#choice-rows input[data-field="key"]').first).to_have_value('manual')
    expect(workspace.locator('#status')).to_have_text('準備完了')
    assert 'answers' not in workspace.evaluate(f'localStorage.getItem("{STORAGE_KEY}")')


def test_delete_saved_question(workspace):
    workspace.locator('#set-name').fill('削除対象')
    workspace.locator('#save').click()
    workspace.once('dialog', lambda dialog: dialog.accept())
    workspace.locator('#delete').click()
    expect(workspace.locator('#saved-set option')).to_have_count(3)
    expect(workspace.locator('#restore')).to_be_disabled()


def test_same_name_overwrite_requires_confirmation(workspace):
    workspace.locator('#set-name').fill('同名セット')
    workspace.locator('#save').click()
    workspace.locator('#state').fill('変更後の本文')
    workspace.once('dialog', lambda dialog: dialog.dismiss())
    workspace.locator('#save').click()
    workspace.locator('#restore').click()
    expect(workspace.locator('#state')).not_to_have_value('変更後の本文')
    workspace.locator('#state').fill('変更後の本文')
    workspace.once('dialog', lambda dialog: dialog.accept())
    workspace.locator('#save').click()
    workspace.locator('#state').fill('別の内容')
    workspace.locator('#restore').click()
    expect(workspace.locator('#state')).to_have_value('変更後の本文')
    expect(workspace.locator('#saved-set option')).to_have_count(4)


def test_corrupt_storage_does_not_prevent_execution(workspace):
    workspace.evaluate(f'localStorage.setItem("{STORAGE_KEY}", "broken json")')
    workspace.reload()
    expect(workspace.locator('#notice')).to_contain_text('保存データを読み込めません')
    expect(workspace.locator('#save')).to_be_disabled()
    mock_decision(workspace)
    workspace.locator('#run').click()
    expect(workspace.locator('#status')).to_have_text('完了')


def test_storage_quota_error(workspace):
    workspace.evaluate('() => { Storage.prototype.setItem = () => { throw new DOMException("quota"); }; }')
    workspace.locator('#set-name').fill('容量不足')
    workspace.locator('#save').click()
    expect(workspace.locator('#notice')).to_contain_text('保存できません')
    expect(workspace.locator('#run')).to_be_enabled()


def test_add_and_remove_rows(workspace):
    workspace.locator('#add-choice').click()
    expect(workspace.locator('#choice-rows .criterion-row')).to_have_count(3)
    workspace.get_by_role('button', name='選択肢 3 を削除', exact=True).click()
    expect(workspace.locator('#choice-rows .criterion-row')).to_have_count(2)
    workspace.get_by_role('button', name='採点基準 2 を削除', exact=True).click()
    expect(workspace.locator('#score-rows .level-number')).to_have_text(['0', '1'])


def test_duplicate_choice_and_all_disabled(workspace):
    workspace.locator('#choice-rows [data-field="key"]').nth(1).fill('manual')
    workspace.locator('#run').click()
    expect(workspace.locator('#notice')).to_contain_text('キーは重複できません')
    for kind in ('noul', 'choice', 'score'):
        workspace.locator(f'#{kind}-enabled').uncheck()
    workspace.locator('#run').click()
    expect(workspace.locator('#notice')).to_contain_text('少なくとも1つ')


def test_failure_and_retry(workspace):
    workspace.route('**/api/decision', lambda route: route.fulfill(
        status=503, json={'detail': '設定を確認してください。'}))
    workspace.locator('#run').click()
    expect(workspace.locator('#notice')).to_have_text('設定を確認してください。')
    expect(workspace.locator('#run')).to_be_enabled()
    workspace.unroute('**/api/decision')
    mock_decision(workspace)
    workspace.locator('#run').click()
    expect(workspace.locator('#status')).to_have_text('完了')


def test_html_strings_are_not_interpreted(workspace):
    text = '<img src=x onerror=alert(1)>'
    workspace.locator('#choice-rows [data-field="description"]').first.fill(text)
    workspace.locator('#set-name').fill(text)
    workspace.locator('#save').click()
    mock_decision(workspace)
    workspace.locator('#run').click()
    expect(workspace.locator('#choice-result .answer-description')).to_have_text(text)
    expect(workspace.locator('#choice-result img')).to_have_count(0)
    expect(workspace.locator('#saved-set option').last).to_have_text(text)


def test_editing_and_restoring_clear_old_results(workspace):
    workspace.locator('#set-name').fill('結果なし')
    workspace.locator('#save').click()
    mock_decision(workspace)
    workspace.locator('#run').click()
    expect(workspace.locator('#raw-response')).to_be_visible()
    workspace.locator('#state').fill('質問を変更')
    expect(workspace.locator('#raw-response')).to_be_hidden()
    workspace.locator('#restore').click()
    expect(workspace.locator('#noul-result')).to_contain_text('未実行')


def test_initialize_samples_once(page, server_url):
    sample = {'id': 'sample-1', 'name': '初期サンプル', 'values': {
        'state': 'サンプルの質問', 'noul': {'enabled': True, 'instructions': '判断してください'},
        'choice': {'enabled': False, 'instructions': '', 'criteria': []},
        'score': {'enabled': False, 'instructions': '', 'criteria': []},
    }}
    page.route('**/static/default-questions.json', lambda route: route.fulfill(
        json={'schemaVersion': 1, 'sets': [sample]}))
    page.goto(server_url)
    expect(page.locator('#saved-set option')).to_have_count(2)
    page.locator('#saved-set').select_option(label='初期サンプル')
    page.locator('#restore').click()
    expect(page.locator('#state')).to_have_value('サンプルの質問')
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#delete').click()
    page.reload()
    expect(page.locator('#library-controls')).to_be_enabled()
    expect(page.locator('#saved-set option')).to_have_count(1)


def test_builtin_samples_restore_exactly(workspace):
    data = json.loads(Path('app/static/default-questions.json').read_text(encoding='utf-8'))
    assert [item['name'] for item in data['sets']] == ['ディープインパクト', '物語文']
    expect(workspace.locator('#saved-set option')).to_have_count(3)
    for sample in data['sets']:
        workspace.locator('#saved-set').select_option(label=sample['name'])
        workspace.locator('#restore').click()
        assert workspace.evaluate('capture()') == sample['values']
        expect(workspace.locator('#status')).to_have_text('準備完了')


@pytest.mark.parametrize('empty', [False, True])
def test_existing_library_is_not_modified(workspace, empty):
    original = workspace.evaluate(f'JSON.parse(localStorage.getItem("{STORAGE_KEY}"))')
    original['sets'] = [] if empty else [original['sets'][0]]
    if not empty:
        original['sets'][0]['name'] = '利用者の編集済み質問'
        original['sets'][0]['values']['state'] = 'この内容を保持する'
    workspace.evaluate('data => localStorage.setItem(data.key, JSON.stringify(data.value))',
                       {'key': STORAGE_KEY, 'value': original})
    workspace.reload()
    expect(workspace.locator('#library-controls')).to_be_enabled()
    assert workspace.evaluate(f'JSON.parse(localStorage.getItem("{STORAGE_KEY}"))') == original
    expect(workspace.locator('#saved-set option')).to_have_count(len(original['sets']) + 1)


def test_sample_download_failure_does_not_block_execution(page, server_url):
    page.route('**/static/default-questions.json', lambda route: route.fulfill(status=503))
    page.goto(server_url)
    expect(page.locator('#notice')).to_contain_text('初期サンプルを保存できませんでした')
    expect(page.locator('#library-controls')).to_be_enabled()
    mock_decision(page)
    page.locator('#run').click()
    expect(page.locator('#status')).to_have_text('完了')