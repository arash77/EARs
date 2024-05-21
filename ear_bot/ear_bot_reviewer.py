import json
import os
import random
import sys
from argparse import ArgumentParser
from datetime import datetime, timedelta

import pytz
from github import Github

cet = pytz.timezone("CET")


class EARBot_artifact:
    def __init__(self) -> None:
        self.artifact_path = os.path.join(
            "ear_bot", os.getenv("ARTIFACT_PATH", "artifact.json")
        )

    def load_pr_data(self):
        save_pr_data = {"pr": {}, "busy_reviewers": []}
        if os.path.exists(self.artifact_path):
            with open(self.artifact_path, "r") as file:
                save_pr_data = json.load(file)
        return save_pr_data

    def dump_pr_data(self, save_pr_data):
        with open(self.artifact_path, "w") as file:
            json.dump(save_pr_data, file, indent=4, default=str)


class EARBotReviewer:
    def __init__(self) -> None:
        g = Github(os.getenv("GITHUB_TOKEN"))
        self.repo = g.get_repo(str(os.getenv("GITHUB_REPOSITORY")))
        self.pull_requests = self.repo.get_pulls(state="open")
        self.closed_pull_requests = self.repo.get_pulls(state="closed")
        reviewers_path = os.path.join(
            "ear_bot", os.getenv("REVIEWERS_PATH", "reviewers.txt")
        )
        if os.path.exists(reviewers_path):
            with open(reviewers_path, "r") as file:
                self.list_of_reviewers = set(map(str.lower, file.read().splitlines()))
        else:
            print("Missing reviewers file.")
            sys.exit(1)
        self.artifact = EARBot_artifact()

    def find_reviewer(self, prs=[], deadline_check=True):
        save_pr_data = self.artifact.load_pr_data()
        if save_pr_data.get("pr"):
            for closed_pr in self.closed_pull_requests:
                closed_pr_number = str(closed_pr.number)
                if closed_pr_number in save_pr_data:
                    del save_pr_data["pr"][closed_pr_number]

        current_date = datetime.now(tz=cet).replace(microsecond=0)

        if not prs:
            prs = self.pull_requests

        for pr in prs:
            if len(pr.requested_reviewers) > 1 or "ERGA-BGE" not in [
                label.name for label in pr.get_labels()
            ]:
                continue
            pr_number = str(pr.number)
            pr_data = save_pr_data["pr"].get(pr_number, {})
            old_reviewers = set(map(str.lower, pr_data.get("requested_reviewers", [])))
            busy_reviewers = set(map(str.lower, save_pr_data.get("busy_reviewers", [])))

            if old_reviewers | busy_reviewers == self.list_of_reviewers:
                old_reviewers = set()
                busy_reviewers = set()
            left_reviewers = self.list_of_reviewers - old_reviewers - busy_reviewers
            date = pr_data.get("date", current_date)
            if deadline_check:
                for comment in pr.get_issue_comments().reversed:
                    text_to_check = (
                        "Please reply to this message only with Yes or No by"
                    )
                    if comment.user.type == "Bot" and text_to_check in comment.body:
                        comment_reviewer = (
                            comment.body.split("Hi @")[1].split(",")[0].lower()
                        )
                        old_reviewers.update(comment_reviewer)
                        date = comment.created_at.astimezone(cet)
                        deadline = date + timedelta(days=7)
                        if deadline > current_date:
                            left_reviewers = set()
                        break

            new_reviewer = set()
            if left_reviewers:
                reviewer = random.choice(list(left_reviewers))
                pr.create_issue_comment(
                    f"👋 Hi @{reviewer}, do you agree to review this assembly?\n\n"
                    "Please reply to this message only with Yes or No by"
                    f" **{current_date + timedelta(days=7)}**"
                )
                new_reviewer = {reviewer}

            save_pr_data["pr"][pr_number] = {
                "date": date,
                "requested_reviewers": list(old_reviewers | new_reviewer),
            }

        self.artifact.dump_pr_data(save_pr_data)

    def assign_reviewer(self):
        comment_text = os.getenv("COMMENT_TEXT").lower()
        comment_author = os.getenv("COMMENT_AUTHOR").lower()
        pr_number = os.getenv("PR_NUMBER")
        if not comment_text or not comment_author or not pr_number:
            print("Missing required environment variables.")
            sys.exit(1)
        pr = self.repo.get_pull(int(pr_number))
        if comment_author in map(
            str.lower, [rr.login for rr in pr.requested_reviewers]
        ):
            print("The reviewer has already been assigned.")
            sys.exit()
        for comment in pr.get_issue_comments().reversed:
            text_to_check = "Please reply to this message only with Yes or No"
            if comment.user.type == "Bot" and text_to_check in comment.body:
                comment_reviewer = comment.body.split("Hi @")[1].split(",")[0].lower()
                break
        if not comment_reviewer:
            print("Missing reviewer from the comment.")
            sys.exit(1)
        if comment_author != comment_reviewer:
            print("The reviewer is not the one who was asked to review the PR.")
            sys.exit(1)
        if "yes" in comment_text:
            supervisor_path = os.path.join(
                "ear_bot", os.getenv("SUPERVISOR_PATH", "supervisor.txt")
            )
            if not os.path.exists(supervisor_path):
                print("Missing supervisor file.")
                sys.exit(1)
            with open(supervisor_path, "r") as file:
                supervisor = file.read().strip()
            pr.create_review_request([comment_author])
            pr.create_issue_comment(
                f"Thank you @{comment_author} for agreeing 👍\n"
                "I appointed you as the EAR reviewer.\n"
                "Please check the Wiki if you need to refresh something.\n"
                f"Contact the @{supervisor} for any issues."
            )
            save_pr_data = self.artifact.load_pr_data()
            if comment_author not in save_pr_data["busy_reviewers"]:
                save_pr_data["busy_reviewers"].append(comment_author)
            self.artifact.dump_pr_data(save_pr_data)
        elif "no" in comment_text:
            self.find_reviewer([pr], deadline_check=False)
        else:
            print("Invalid comment text.")
            sys.exit(1)


def remove_reviewer():
    artifact = EARBot_artifact()
    reviewer = os.getenv("REVIEWER").lower()
    if reviewer not in artifact.load_pr_data()["busy_reviewers"]:
        print("The reviewer is not busy.")
        sys.exit()
    save_pr_data = artifact.load_pr_data()
    save_pr_data["busy_reviewers"].remove(reviewer)
    artifact.dump_pr_data(save_pr_data)


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
    group.add_argument(
        "--remove",
        action="store_true",
        help="Remove the busy reviewer from the PR.",
    )
    args = parser.parse_args()
    if args.search:
        EARBot = EARBotReviewer()
        EARBot.find_reviewer()
    elif args.comment:
        EARBot = EARBotReviewer()
        EARBot.assign_reviewer()
    elif args.remove:
        remove_reviewer()
    else:
        parser.print_help()
        sys.exit(1)
