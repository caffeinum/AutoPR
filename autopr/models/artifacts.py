import typing

import pydantic
from typing_extensions import TypeAlias


class Message(pydantic.BaseModel):
    body: str
    author: str

    def to_str(self):
        return f"{self.author}: {self.body}\n\n"


class Thread(pydantic.BaseModel):
    messages: list[Message]

    def to_str(self):
        return "\n".join(message.to_str() for message in self.messages)


class Issue(Thread):
    number: int
    title: str
    author: str

    def to_str(self):
        return f"#{self.number} {self.title}\n\n" + "\n".join(
            message.to_str() for message in self.messages
        )


class CodeReview(Thread):
    commit_sha: str
    filepath: str
    status: typing.Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"]

    start_line_number: int
    end_line_number: typing.Optional[int] = None

    def to_str(self):
        return f"{self.commit_sha}\n" \
               f"{self.filepath}:L{self.start_line_number}" + f"{f'-L{self.end_line_number}' if self.end_line_number else ''}\n" \
               f"{self.status}\n\n" + "\n".join(message.to_str() for message in self.messages)


class PullRequest(Issue):
    base_branch: str
    head_branch: str
    code_review_threads: list[CodeReview]

    def to_str(self):
        return f"#{self.number} {self.title}\n\n" + "\n".join(
            message.to_str() for message in self.messages
        ) + "\n\n" + "\n".join(
            thread.to_str() for thread in self.code_review_threads
        )


DiffStr: TypeAlias = str
