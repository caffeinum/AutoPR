from typing import Literal, Union

import pydantic

from autopr.models.artifacts import Issue, Message, PullRequest, CodeReview


class Event(pydantic.BaseModel):
    event_type: str


class IssueOpenedEvent(Event):
    event_type: Literal['issue_opened'] = 'issue_opened'

    issue: Issue


class IssueCommentEvent(Event):
    event_type: Literal['issue_closed'] = 'issue_closed'

    issue: Issue
    new_comment: Message


class PullRequestCommentEvent(Event):
    event_type: Literal['pull_request_comment'] = 'pull_request_comment'

    pull_request: PullRequest
    new_comment: Message


class CodeReviewCommentEvent(Event):
    event_type: Literal['code_review_comment'] = 'code_review_comment'

    pull_request: PullRequest
    code_review: CodeReview
    new_comment: Message


EventUnion = Union[tuple(Event.__subclasses__())]  # type: ignore
