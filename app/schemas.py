from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

LIMITS = {'state': 20000, 'instructions': 2000, 'criteria': 2000, 'key': 64, 'rows': 20}
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Criterion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Key = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r'^[A-Za-z0-9_-]{1,64}$')]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Question(Model):
    enabled: bool = False
    instructions: Text = ''


class NoulInput(Question):
    @model_validator(mode='after')
    def require_instructions(self) -> Self:
        if self.enabled and not self.instructions:
            raise ValueError('Noul の指示文を入力してください。')
        return self


class Option(Model):
    key: Key
    description: Criterion


class ChoiceInput(Question):
    criteria: list[Option] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def check_choices(self) -> Self:
        if self.enabled and not self.criteria:
            raise ValueError('Choice の選択肢を入力してください。')
        keys = [option.key for option in self.criteria]
        if self.enabled and len(keys) != len(set(keys)):
            raise ValueError('Choice のキーは重複できません。')
        return self


class ScoreInput(Question):
    criteria: list[Criterion] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def check_rubric(self) -> Self:
        if self.enabled and not self.criteria:
            raise ValueError('Score の採点基準を入力してください。')
        return self


class DecisionInput(Model):
    state: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
    noul: NoulInput = Field(default_factory=NoulInput)
    choice: ChoiceInput = Field(default_factory=ChoiceInput)
    score: ScoreInput = Field(default_factory=ScoreInput)

    @model_validator(mode='after')
    def require_question(self) -> Self:
        if not any(question.enabled for question in (self.noul, self.choice, self.score)):
            raise ValueError('少なくとも1つの質問形式を有効にしてください。')
        return self