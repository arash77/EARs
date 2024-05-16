import json
import os
import random
import sys
from argparse import ArgumentParser
from datetime import datetime, timedelta

import pytz
from github import Github

cet = pytz.timezone("CET")


g = Github(os.getenv("GITHUB_TOKEN"))
repo = g.get_repo(f"{os.getenv('GITHUB_REPOSITORY')}")
pull_requests = repo.get_pulls(state="open")
closed_pull_requests = repo.get_pulls(state="closed")
artifact_path = os.path.join("ear_bot", os.getenv("ARTIFACT_PATH", "artifact.json"))
reviewers_path = os.path.join("ear_bot", os.getenv("REVIEWERS_PATH", "reviewers.txt"))
if os.path.exists(reviewers_path):
    with open(reviewers_path, "r") as file:
        list_of_reviewers = file.read().splitlines()
else:
    print("Missing reviewers file.")
    sys.exit(1)



def find_reviewer(prs=[], deadline_check=True):
    save_pr_data = {}
    if os.path.exists(artifact_path):
        with open(artifact_path, "r") as file:
            save_pr_data = json.load(file)
    if save_pr_data and not prs:
        for closed_pr in closed_pull_requests:
            closed_pr_number = str(closed_pr.number)
            if closed_pr_number in save_pr_data:
                del save_pr_data[closed_pr_number]

    current_date = datetime.now(tz=cet).replace(microsecond=0)

    if not prs:
        prs = pull_requests

    for pr in prs:
        if len(pr.requested_reviewers) > 1:
            continue
        pr_number = str(pr.number)
        pr_data = save_pr_data.get(pr_number, {})
        old_reviewers = pr_data.get("requested_reviewers", [])
        if set(old_reviewers) == set(list_of_reviewers):
            old_reviewers = []  # Reset the reviewers if all reviewers have been asked
        left_reviewers = list(set(list_of_reviewers) - set(old_reviewers))
        date = pr_data.get("date", current_date)
        if deadline_check:
            for comment in pr.get_issue_comments().reversed:
                text_to_check = "Please reply to this message only with Yes or No by"
                if comment.user.type == "Bot" and text_to_check in comment.body:
                    comment_reviewer = comment.body.split("Hi @")[1].split(",")[0]
                    old_reviewers.append(comment_reviewer) if comment_reviewer not in old_reviewers else None
                    date = comment.created_at.astimezone(cet)
                    deadline = date + timedelta(days=7)
                    if deadline > current_date:
                        left_reviewers = []
                    break

        new_reviewer = []
        if left_reviewers:
            reviewer = random.choice(left_reviewers)
            pr.create_issue_comment(
                f"👋 Hi @{reviewer}, do you agree to review this assembly?\n\n"
                + "Please reply to this message only with Yes or No by"
                + f" {current_date + timedelta(days=7)}"
            )
            new_reviewer = [reviewer]

        save_pr_data[pr_number] = {
            "date": date,
            "requested_reviewers": old_reviewers + new_reviewer,
        }
    with open(artifact_path, "w") as file:
        json.dump(save_pr_data, file, indent=4, default=str)


def assign_reviewer():
    comment_text = os.getenv("COMMENT_TEXT")
    comment_author = os.getenv("COMMENT_AUTHOR")
    pr_number = os.getenv("PR_NUMBER")
    if not comment_text or not comment_author or not pr_number:
        print("Missing required environment variables.")
        sys.exit(1)
    pr = repo.get_pull(int(pr_number))
    if comment_author in [rr.login for rr in pr.requested_reviewers]:
        print("The reviewer has already been assigned.")
        sys.exit()
    for comment in pr.get_issue_comments().reversed:
        text_to_check = "Please reply to this message only with Yes or No by"
        if comment.user.type == "Bot" and text_to_check in comment.body:
            comment_reviewer = comment.body.split("Hi @")[1].split(",")[0]
            break
    if comment_author != comment_reviewer:
        print("The reviewer is not the one who was asked to review the PR.")
        sys.exit(1)
    if "yes" in comment_text.lower():
        pr.create_review_request([comment_author])
    elif "no" in comment_text.lower():
        find_reviewer([pr], deadline_check=False)
    else:
        print("Invalid comment text.")
        sys.exit(1)


if __name__ == "__main__":
    parser = ArgumentParser(description="EAR bot!")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--search", action="store_true", help="Search for a reviewer if needed."
    )
    group.add_argument(
        "--comment",
        action="store_true",
        help="Assign the reviewer to the PR when the reviewer agrees.",
    )
    args = parser.parse_args()
    if args.search:
        find_reviewer()
    elif args.comment:
        assign_reviewer()
    else:
        parser.print_help()
        sys.exit(1)
