import json
import sys
import traceback
from typing import Optional, Union, Any

import pydantic
import requests

from autopr.models.artifacts import Issue
from autopr.models.rail_objects import PullRequestDescription, CommitPlan

import structlog


class UpdateSection(pydantic.BaseModel):
    level: int
    title: str
    updates: list[Union[str, 'UpdateSection']] = pydantic.Field(default_factory=list)
    result: Optional[str] = None


class PublishService:
    def __init__(
        self,
        issue: Issue,
        loading_gif_url: str = "https://media0.giphy.com/media/l3nWhI38IWDofyDrW/giphy.gif",
    ):
        self.issue = issue
        self.loading_gif_url = loading_gif_url

        self.pr_desc: PullRequestDescription = self._create_placeholder(issue)
        self.sections_stack: list[UpdateSection] = [
            UpdateSection(
                level=0,
                title="root",
            )
        ]
        self.sections_list: list[UpdateSection] = []

        self.log = structlog.get_logger(service="publish")

        self.issue_template = """
## Traceback

```
{error}
```
"""
        self.issue_link_template = "https://github.com/irgolic/AutoPR/issues/new?" \
                                   "title={title}&" \
                                   "labels=bug&" \
                                   "body={body}"

    def _create_placeholder(self, issue: Issue) -> PullRequestDescription:
        return PullRequestDescription(
            title=f"Fix #{issue.number}: {issue.title}",
            body="",
            commits=[],
        )

    def publish_call(
        self,
        summary: str,
        section_title: Optional[str] = None,
        default_open=('response',),
        **kwargs
    ):
        subsections = []
        for k, v in kwargs.items():
            # Cast keys to title case
            title = k.title()
            title = title.replace("_", " ")

            # Prefix content with quotation marks and A ZERO-WIDTH SPACE (!!!) to prevent escaping backticks
            content = '\n'.join([
                f"    {line}" for line in v.splitlines()
            ])

            # Construct subsection
            subsection = f"""<details{" open" if k in default_open else ""}>
<summary>{title}</summary>

{content}
</details>"""
            subsections.append(subsection)

        # Concatenate subsections
        subsections_content = '\n\n'.join(subsections)

        # Prefix them with a quotation mark
        subsections_content = '\n'.join([f"> {line}" for line in subsections_content.splitlines()])

        # Construct progress string
        progress_str = f"""<details>
<summary>{summary}</summary>

{subsections_content}

</details>
"""
        self.publish_update(progress_str, section_title=section_title)

    def set_pr_description(self, pr: PullRequestDescription):
        self.pr_desc = pr
        self.update()

    def publish_update(
        self,
        text: str,
        section_title: Optional[str] = None,
    ):
        self.sections_stack[-1].updates.append(text)
        if section_title:
            if len(self.sections_stack) == 1:
                raise ValueError("Cannot set section title on root section")
            self.sections_stack[-1].title = section_title
        self.log.debug("Publishing update", text=text)
        self.update()

    def start_section(
        self,
        title: str,
    ):
        self.log.debug("Starting section", title=title)
        new_section = UpdateSection(
            level=len(self.sections_stack),
            title=title,
        )
        self.sections_stack[-1].updates.append(new_section)  # Add the new section as a child
        self.sections_stack.append(new_section)
        self.update()

    def update_section(self, title: str):
        if len(self.sections_stack) == 1:
            raise ValueError("Cannot set section title on root section")
        self.log.debug("Updating section", title=title)
        self.sections_stack[-1].title = title
        self.update()

    def end_section(
        self,
        title: Optional[str] = None,
        result: Optional[str] = None,
    ):
        if len(self.sections_stack) == 1:
            raise ValueError("Cannot end root section")
        self.log.debug("Ending section", title=title)
        if title:
            self.sections_stack[-1].title = title
        self.sections_stack[-1].result = result
        self.sections_stack.pop()

        self.update()

    def _build_progress_update(self, section: UpdateSection, finalize: bool = False) -> str:
        if section.level == 0:
            return '\n\n'.join(
                self._build_progress_update(s, finalize=finalize)
                if isinstance(s, UpdateSection)
                else s
                for s in section.updates
            )

        progress = ""
        # Get list of steps
        updates = []
        for update in section.updates:
            if isinstance(update, UpdateSection):
                # Recursively build updates
                updates += [self._build_progress_update(update, finalize=finalize)]
                continue
            updates += [update]

        # Add result as an open section at the end of updates
        if section.result:
            result = '\n'.join([f"> {line}" for line in section.result.splitlines()])
            updates += [f"""<details open>
<summary>📝 Result</summary>

{result}
</details>"""]

        # Prefix updates with quotation
        updates = '\n\n'.join(updates)
        updates = '\n'.join([f"> {line}" for line in updates.splitlines()])

        progress += f"""<details>
<summary>{section.title}</summary>

{updates}
</details>"""

        return progress

    def _build_progress_updates(self, finalize: bool = False):
        progress = self._build_progress_update(self.sections_stack[0], finalize=finalize)
        if not finalize:
            progress += f"\n\n" \
                        f'<img src="{self.loading_gif_url}"' \
                        f' width="200" height="200"/>'
        return f"## Progress Updates\n\n{progress}"

    def _build_issue_template_link(self, **kwargs):
        error = "No traceback" if sys.exc_info()[0] is None else traceback.format_exc()
        kwargs['error'] = error

        body = self.issue_template.format(**kwargs)
        if sys.exc_info()[0] is not None:
            title = traceback.format_exception_only(sys.exc_info()[0], sys.exc_info()[1])[0].strip()
        else:
            title = f'Error fixing "{self.issue.title}"'

        issue_link = self.issue_link_template.format(
            body=body,
            title=title,
        )
        return (
            issue_link.replace(' ', '%20')
            .replace('\n', '%0A')
            .replace('"', '%22')
            .replace("#", "%23")
        )

    def _build_body(self, success: Optional[bool] = None):
        # Add Fixes magic word
        body = f"Fixes #{self.issue.number}"

        # Build PR description
        if self.pr_desc.body:
            body += f"\n\n## Description\n\n" \
                        f"{self.pr_desc.body}"

        # Build status
        body += f"\n\n## Status\n\n"
        if success is None:
            body += "This pull request is being autonomously generated by [AutoPR](https://github.com/irgolic/AutoPR)."
        elif not success:
            body += 'This pull request was being autonomously generated by [AutoPR](https://github.com/irgolic/AutoPR), but it encountered an error.'
            if sys.exc_info()[0] is not None:
                body += f"\n\nError:\n\n```\n{traceback.format_exc()}\n```"
            body += f'\n\nPlease <a href="{self._build_issue_template_link()}">open an issue</a> to report this.'
        else:
            body += f"This pull request was autonomously generated by [AutoPR](https://github.com/irgolic/AutoPR).\n\n" \
                        f"If there's a problem with this pull request, please " \
                        f"[open an issue]({self._build_issue_template_link()})."

        if progress := self._build_progress_updates(finalize=success is not None):
            body += f"\n\n{progress}"
        return body

    def update(self):
        body = self._build_body()
        title = self.pr_desc.title
        self._publish(title, body)

    def finalize(self, success: bool):
        body = self._build_body(success=success)
        title = self.pr_desc.title
        self._publish(title, body, success=success)

    def _publish(
        self,
        title: str,
        body: str,
        success: bool = False,
    ):
        raise NotImplementedError


class GithubPublishService(PublishService):
    def __init__(
        self,
        issue: Issue,
        loading_gif_url: str,
        token: str,
        owner: str,
        repo_name: str,
        head_branch: str,
        base_branch: str,
        run_id: str,
    ):
        super().__init__(issue, loading_gif_url)
        self.token = token
        self.owner = owner
        self.repo = repo_name
        self.head_branch = head_branch
        self.base_branch = base_branch
        self.run_id = run_id

        self._drafts_supported = True
        self._pr_number = None

        self.issue_template = """
{shield}

AutoPR encountered an error while trying to fix {issue_link}.

""" + self.issue_template

    def _get_headers(self):
        return {
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }

    def _get_shield(self, success: Optional[bool] = None):
        action_url = f'https://github.com/{self.owner}/{self.repo}/actions/runs/{self.run_id}'
        if success is None:
            return f"[![AutoPR Running](https://img.shields.io/badge/AutoPR-running-yellow)]({action_url})"
        elif success:
            return f"[![AutoPR Success](https://img.shields.io/badge/AutoPR-success-brightgreen)]({action_url})"
        else:
            return f"[![AutoPR Failure](https://img.shields.io/badge/AutoPR-failure-red)]({action_url})"

    def _build_issue_template_link(self, **kwargs):
        shield = self._get_shield(success=False)
        kwargs['shield'] = shield
        issue_link = f"https://github.com/{self.owner}/{self.repo}/issues/{self.issue.number}"
        kwargs['issue_link'] = issue_link
        return super()._build_issue_template_link(**kwargs)

    def _build_body(self, success: Optional[bool] = None):
        # Make shield
        shield = self._get_shield(success=success)

        body = super()._build_body(success=success)
        return shield + '\n\n' + body

    def _publish(self, title: str, body: str, success: bool = False):
        if existing_pr := self._find_existing_pr():
            self._update_pr(existing_pr, title, body, success)
        else:
            self._create_pr(title, body, success)

    def _create_pr(self, title: str, body: str, success: bool):
        url = f'https://api.github.com/repos/{self.owner}/{self.repo}/pulls'
        headers = self._get_headers()
        data = {
            'head': self.head_branch,
            'base': self.base_branch,
            'title': title,
            'body': body,
        }
        if self._drafts_supported:
            data['draft'] = "false" if success else "true"
        response = requests.post(url, json=data, headers=headers)

        if response.status_code == 201:
            self.log.debug('Pull request created successfully',
                           response=response.json(),
                           headers=response.headers)
            return

        # if draft pull request is not supported
        if self._is_draft_error(response.text):
            del data['draft']
            response = requests.post(url, json=data, headers=headers)
            if response.status_code == 201:
                self.log.debug('Pull request created successfully',
                               response=response.json(),
                               headers=response.headers)
                return
        self.log.error('Failed to create pull request',
                       code=response.status_code,
                       response=response.json(),
                       headers=response.headers)

    def _is_draft_error(self, response_text: str):
        response_obj = json.loads(response_text)
        is_draft_error = 'message' in response_obj and \
            'draft pull requests are not supported' in response_obj['message'].lower()
        if is_draft_error:
            self.log.warning("Pull request drafts error on this repo")
            self._drafts_supported = False
        return is_draft_error

    def _set_pr_draft_status(self, pull_request_node_id: str, is_draft: bool):
        # sadly this is only supported by graphQL
        if is_draft:
            graphql_query = '''
                mutation ConvertPullRequestToDraft($pullRequestId: ID!) {
                  convertPullRequestToDraft(input: { pullRequestId: $pullRequestId }) {
                    clientMutationId
                  }
                }
            '''
        else:
            graphql_query = '''
                mutation MarkPullRequestReadyForReview($pullRequestId: ID!) {
                  markPullRequestReadyForReview(input: { pullRequestId: $pullRequestId }) {
                    clientMutationId
                  }
                }
            '''
        headers = self._get_headers() | {
            'Content-Type': 'application/json'
        }

        # Undraft the pull request
        data = {'pullRequestId': pull_request_node_id}
        response = requests.post(
            'https://api.github.com/graphql',
            headers=headers,
            json={'query': graphql_query, 'variables': data}
        )

        if response.status_code == 200:
            self.log.debug('Pull request draft status updated successfully',
                           response=response.json(),
                           headers=response.headers)
            return

        self.log.error('Failed to update pull request draft status',
                       code=response.status_code,
                       response=response.json(),
                       headers=response.headers)
        self._drafts_supported = False

    def _update_pr(self, existing_pr: dict[str, Any], title: str, body: str, success: bool):
        pr_number = existing_pr['number']
        url = f'https://api.github.com/repos/{self.owner}/{self.repo}/pulls/{pr_number}'
        headers = self._get_headers()
        data = {
            'title': title,
            'body': body,
        }
        response = requests.patch(url, json=data, headers=headers)

        if response.status_code == 200:
            self.log.debug('Pull request updated successfully',
                           response=response.json(),
                           headers=response.headers)
            # Update draft status
            if self._drafts_supported:
                self._set_pr_draft_status(existing_pr['node_id'], not success)
            return

        self.log.error('Failed to update pull request',
                       code=response.status_code,
                       response=response.json(),
                       headers=response.headers)

    def _find_existing_pr(self):
        """
        Returns the PR dict of the first open pull request with the same head and base branches
        """
        url = f'https://api.github.com/repos/{self.owner}/{self.repo}/pulls'
        headers = self._get_headers()
        params = {'state': 'open', 'head': f'{self.owner}:{self.head_branch}', 'base': self.base_branch}
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            if prs := response.json():
                return prs[0]  # Return the first pull request found
        else:
            self.log.error('Failed to get pull requests', response_text=response.text)

        return None
