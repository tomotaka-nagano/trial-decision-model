from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential, DefaultAzureCredential, get_bearer_token_provider
from exmgai.config import get_model, load_config
from exmgai.decision import Decision
from exmgai.providers.foundry import FoundryDecisionProvider
from pydantic import ValidationError
from typesafe_sdk import Choice, Noul, Score, TypeSafeError

from app.schemas import DecisionInput

ROOT = Path(__file__).resolve().parent.parent


class ServiceError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def build_questions(request: DecisionInput) -> dict:
    questions = {}
    if request.noul.enabled:
        questions['approve'] = Noul(instructions=request.noul.instructions)
    if request.choice.enabled:
        criteria = {item.key: item.description for item in request.choice.criteria}
        questions['route'] = Choice(criteria=criteria, instructions=request.choice.instructions or None)
    if request.score.enabled:
        questions['risk'] = Score(criteria=request.score.criteria, instructions=request.score.instructions or None)
    return questions


def auth_headers(auth, model, stack: ExitStack):
    if auth.type == 'api_key' and model.api_key:
        return lambda: {'api-key': model.api_key}
    if auth.type != 'entra_id' or auth.credential not in ('azure_cli', 'default'):
        raise ValueError('Invalid authentication settings')
    credential_type = AzureCliCredential if auth.credential == 'azure_cli' else DefaultAzureCredential
    credential = stack.enter_context(credential_type(process_timeout=30))
    token = get_bearer_token_provider(credential, 'https://cognitiveservices.azure.com/.default')
    return lambda: {'Authorization': f'Bearer {token()}'}


def validated_model(config):
    model = get_model('decision', config)
    endpoint = urlsplit(model.endpoint)
    if model.provider != 'foundry' or endpoint.scheme != 'https' or not endpoint.hostname:
        raise ValueError('Invalid Foundry model settings')
    if not model.deployment.strip() or not 1 <= model.read_timeout <= 600 or model.input_token_cost < 0:
        raise ValueError('Invalid deployment, timeout or cost')
    return model


@contextmanager
def configured_decision():
    config = load_config(ROOT / 'env.toml')
    model = validated_model(config)
    with ExitStack() as stack:
        headers = auth_headers(config.auth, model, stack)
        transport = stack.enter_context(httpx2.Client())
        provider = FoundryDecisionProvider(model.endpoint, headers, model.read_timeout, client=transport)
        yield Decision(provider, model.deployment, model.input_token_cost), model.input_token_cost > 0


def normalize(response, questions: dict, priced: bool) -> dict:
    if set(response.answers) != set(questions):
        raise ServiceError(502, 'モデルの回答に必要な項目がありません。')
    if any(response.answers[key].type != question.type for key, question in questions.items()):
        raise ServiceError(502, 'モデルの回答形式が一致しません。')
    return {
        'model': response.model,
        'answers': {key: value.model_dump(mode='json') for key, value in response.answers.items()},
        'input_tokens': response.usage.input_tokens,
        'estimated_cost_usd': response.cost() if priced and response.usage.input_tokens is not None else None,
    }


def execute(request: DecisionInput) -> dict:
    try:
        with configured_decision() as (client, priced):
            questions = build_questions(request)
            return normalize(client.system_one(state=request.state, questions=questions), questions, priced)
    except (httpx2.TimeoutException, TimeoutError):
        message = 'モデルの応答がタイムアウトしました。再実行には追加の費用が発生する場合があります。'
        raise ServiceError(504, message) from None
    except ClientAuthenticationError:
        raise ServiceError(503, 'モデルの認証に失敗しました。管理者に接続設定の確認を依頼してください。') from None
    except (TypeSafeError, httpx2.HTTPError, ValidationError):
        raise ServiceError(502, 'モデルへの接続または回答の取得に失敗しました。') from None
    except (OSError, ValueError, KeyError):
        raise ServiceError(503, 'モデルの設定を読み込めません。管理者に接続設定の確認を依頼してください。') from None