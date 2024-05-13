from datetime import datetime, timedelta, timezone
from github import Github
import os
import json
import pytz
import random

cet = pytz.timezone("CET")


g = Github(os.getenv("GITHUB_TOKEN"))
repo = g.get_repo(f"{os.getenv('GITHUB_REPOSITORY')}")
pull_requests = repo.get_pulls(state="open")
closed_pull_requests = repo.get_pulls(state="closed")
list_of_reviewers = os.getenv("REVIEWERS", "").split(",")
artifact_path = os.path.join("ear_bot", os.getenv("ARTIFACT_PATH", "artifact.json"))


def comment_to_random_reviewer(pr, reviewers):
    if not reviewers:
        return []
    reviewer = random.choice(reviewers)
    current_date = datetime.now(tz=cet).replace(microsecond=0)
    pr.create_issue_comment(
        f"👋 Hi @{reviewer}, do you agree to review this assembly?\n\nPlease reply to this message only with Yes or No by {current_date + timedelta(days=7)}"
    )
    return [reviewer]


def main():
    save_pr_data = {}
    if os.path.exists(artifact_path):
        with open(artifact_path, "r") as file:
            save_pr_data = json.load(file)
        for closed_pr in closed_pull_requests:
            closed_pr_number = str(closed_pr.number)
            if closed_pr_number in save_pr_data:
                del save_pr_data[closed_pr_number]

    current_date = datetime.now(tz=cet).replace(microsecond=0)
    for pr in pull_requests:
        pr_number = str(pr.number)
        if len(pr.requested_reviewers) < 2:
            left_reviewers = list_of_reviewers
            old_reviewers = save_pr_data.get(pr_number, {}).get(
                "requested_reviewers", []
            )
            comment_date = save_pr_data.get(pr_number, {}).get("date")
            for comment in pr.get_issue_comments().reversed:
                text_to_check = "Please reply to this message only with Yes or No by"
                if comment.user.type == "Bot" and text_to_check in comment.body:
                    comment_date = comment.created_at.astimezone(cet)
                    deadline = comment_date + timedelta(days=7)
                    comment_date = comment_date.isoformat()
                    left_reviewers = (
                        list(set(list_of_reviewers) - set(old_reviewers))
                        if deadline < current_date
                        else []
                    )
                    break
            new_reviewer = comment_to_random_reviewer(pr, left_reviewers)
            save_pr_data[pr_number] = {
                "date": (
                    current_date.isoformat()
                    if new_reviewer or not comment_date
                    else comment_date
                ),
                "requested_reviewers": old_reviewers + new_reviewer,
            }
    with open(artifact_path, "w") as file:
        json.dump(save_pr_data, file, indent=4)


if __name__ == "__main__":
    main()
