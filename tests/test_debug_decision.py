import json
from types import SimpleNamespace

import pytest
from exmgai.decision import DecisionResponse

from debug import debug_decision


def test_debug_connection_success(monkeypatch, capsys):
    calls, clients = [], []

    def system_one(**kwargs):
        calls.append(kwargs)
        return DecisionResponse.model_validate({
            'model': 'Microsoft-Decision-1', 'usage': {'input_tokens': 10},
            'answers': {'approve': {'type': 'noul', 'noul': 0.99}},
        })

    def create_client(model_name, *, env):
        clients.append((model_name, env))
        return SimpleNamespace(decision=SimpleNamespace(system_one=system_one))

    monkeypatch.setattr(debug_decision, 'Client', create_client)
    debug_decision.main()
    output = capsys.readouterr().out
    result = json.loads(output[output.index('{'):])
    assert 'Connection successful.' in output
    assert result['answers']['approve']['noul'] == 0.99
    assert result['model'] == 'Microsoft-Decision-1'
    assert result['usage']['input_tokens'] == 10
    assert len(calls) == 1
    assert calls[0]['state'] == '2 is an even number.'
    assert set(calls[0]['questions']) == {'approve'}
    assert calls[0]['questions']['approve'].instructions == 'Is this statement correct?'
    assert clients == [('decision', debug_decision.ROOT / 'env.toml')]


def test_debug_connection_failure_is_not_hidden(monkeypatch, capsys):
    error = RuntimeError('Connection failed')
    def system_one(**kwargs):
        raise error

    def create_client(model_name, *, env):
        return SimpleNamespace(decision=SimpleNamespace(system_one=system_one))

    monkeypatch.setattr(debug_decision, 'Client', create_client)
    with pytest.raises(RuntimeError) as caught:
        debug_decision.main()
    assert caught.value is error
    assert 'Connection successful.' not in capsys.readouterr().out
