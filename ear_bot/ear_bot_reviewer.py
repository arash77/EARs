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
list_of_reviewers = os.getenv("REVIEWERS", "").split(",")
artifact_path = os.path.join('ear_bot', os.getenv("ARTIFACT_PATH", "artifact.json"))


def comment_to_random_reviewer(pr):
    # get the not chosen reviewers and then choose one randomly
    reviewer = random.choice(list_of_reviewers)
    current_date = datetime.now(tz=cet).replace(microsecond=0)
    pr.create_issue_comment(
        f"👋 Hi @{reviewer}, do you agree to review this assembly?\n\nPlease reply to this message only with Yes or No by {current_date + timedelta(days=7)}"
    )


def main():
    save_pr_data = []
    if os.path.exists(artifact_path):
        with open(artifact_path, "r") as file:
            save_pr_data = json.load(file)

    current_date = datetime.now(tz=cet).replace(microsecond=0)
    # set to central european time
    for pr in pull_requests:
        if len(pr.requested_reviewers) < 2:
            for comment in pr.get_issue_comments().reversed:
                if comment.user.type == "Bot":
                    text_to_check = (
                        "Please reply to this message only with Yes or No by"
                    )
                    if text_to_check in comment.body:
                        date_in_text = comment.body.split(text_to_check)[1].strip()
                        # use this to convert the date to the same timezone as the current date (CET)
                        if comment.created_at + timedelta(days=7) < current_date:
                            comment_to_random_reviewer(pr)
                        break
        # save the pr data only if it was not saved before
        # if the new reviewer was added, the data will be updated
        if not any(pr_data["pr_number"] == pr.number for pr_data in save_pr_data):
            save_pr_data.append(
                {
                    "pr_number": pr.number,
                    "date": current_date.isoformat(),
                    "requested_reviewers": [
                        reviewer.login for reviewer in pr.requested_reviewers
                    ],
                }
            )
    with open(artifact_path, "w") as file:
        json.dump(save_pr_data, file, indent=4)
        


if __name__ == "__main__":
    main()
