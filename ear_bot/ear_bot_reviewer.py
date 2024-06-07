import os
import re
import sys
from argparse import ArgumentParser
from datetime import datetime, timedelta

import pytz
from github import Github

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rev")))
import get_EAR_reviewer  # type: ignore

cet = pytz.timezone("CET")


class EAR_get_reviewer:
    def __init__(self) -> None:
        self.csv_folder = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "rev")
        )
        self.csv_file = os.path.join(self.csv_folder, "reviewers_list.csv")
        if not os.path.exists(self.csv_file):
            raise Exception("The CSV file does not exist.")
        with open(self.csv_file, "r") as file:
            csv_data = file.read()
        if not csv_data:
            raise Exception("The CSV file is empty.")
        self.data = get_EAR_reviewer.parse_csv(csv_data)

    def get_supervisor(self, user):
        selected_supervisor = get_EAR_reviewer.select_random_supervisor(self.data, user)
        if not selected_supervisor:
            raise Exception("No eligible supervisors found.")
        return selected_supervisor.get("Github ID")

    def get_reviewer(self, institution):
        all_eligible_candidates, _, _ = get_EAR_reviewer.select_best_reviewer(
            self.data, institution, "ERGA-BGE"
        )
        if not all_eligible_candidates:
            raise Exception("No eligible candidates found.")
        top_candidates = [
            candidate.get("Github ID").lower() for candidate in all_eligible_candidates
        ]
        return top_candidates

    def add_pr(self, name, institution, species, pr):
        ear_reviews_csv_file = os.path.join(self.csv_folder, "EAR_reviews.csv")
        if not os.path.exists(ear_reviews_csv_file):
            raise Exception("The EAR reviews CSV file does not exist.")
        with open(ear_reviews_csv_file, "a") as file:
            file.write(f"{name},{institution},{species},{pr}\n")

    def update_reviewers_list(
        self,
        reviewer,
        busy,
        institution=None,
        submitted_at=None,
        old_reviewers=[],
    ):
        for reviewer_data in self.data:
            if reviewer_data["Github ID"].lower() == reviewer:
                reviewer_data["Busy"] = "Y" if busy else "N"
                if submitted_at:
                    reviewer_data["Calling Score"] = str(
                        int(reviewer_data["Calling Score"]) - 1
                    )
                    reviewer_data["Total Reviews"] = str(
                        int(reviewer_data["Total Reviews"]) + 1
                    )
                    reviewer_data["Last Review"] = submitted_at
                else:
                    break
            elif reviewer_data["Github ID"].lower() in old_reviewers:
                reviewer_data["Calling Score"] = str(
                    int(reviewer_data["Calling Score"]) + 1
                )
            if reviewer_data["Institution"].lower() == institution.lower():
                reviewer_data["Calling Score"] = str(
                    int(reviewer_data["Calling Score"]) + 1
                )
        else:
            raise Exception("Reviewer not found.")

        csv_str = ",".join(self.data[0].keys()) + "\n"
        for row in self.data:
            csv_str += ",".join(row.values()) + "\n"
        with open(self.csv_file, "w") as file:
            file.write(csv_str)


class EARBotReviewer:
    def __init__(self) -> None:
        g = Github(os.getenv("GITHUB_TOKEN"))
        self.repo = g.get_repo(str(os.getenv("GITHUB_REPOSITORY")))
        self.EAR_reviewer = EAR_get_reviewer()
        self.pr_number = os.getenv("PR_NUMBER")
        self.comment_text = os.getenv("COMMENT_TEXT")
        self.comment_author = os.getenv("COMMENT_AUTHOR")
        self.reviewer = os.getenv("REVIEWER")

    def find_reviewer(self, prs=[], deadline_check=True):
        if not prs:
            prs = list(self.repo.get_pulls(state="open"))

        current_date = datetime.now(tz=cet)

        for pr in prs:
            if (
                len(pr.requested_reviewers) > 1
                or "ERGA-BGE" not in [label.name for label in pr.get_labels()]
                or pr.get_reviews().totalCount > 0
            ):
                continue
            old_reviewers = []
            deadline_passed = False
            for comment in pr.get_issue_comments().reversed:
                text_to_check = "Please reply to this message"
                if comment.user.type == "Bot" and text_to_check in comment.body:
                    comment_reviewer = (
                        re.search(r"@(\w+)", comment.body).group(1).lower()
                    )
                    if not old_reviewers:
                        last_comment_date = comment.created_at.astimezone(cet)
                        deadline_passed = (
                            last_comment_date + timedelta(days=7) < current_date
                        )
                    old_reviewers.append(comment_reviewer)

            institution = re.search(r"Affiliation:\s*(\S+)", pr.body)
            species = re.search(r"Species:\s*(.+)", pr.body)
            if not institution or not species:
                pr.create_issue_comment(
                    "Missing affiliation or species in the PR description."
                )
                continue

            institution = institution.group(1)
            list_of_reviewers = self.EAR_reviewer.get_reviewer(institution)

            if set(list_of_reviewers).issubset(set(old_reviewers)):
                old_reviewers.clear()

            assign_new_reviewer = False
            if deadline_passed:
                assign_new_reviewer = True
                pr.create_issue_comment(
                    "Time is out! I will look for the next reviewer on the list :)"
                )
            if not deadline_check:
                assign_new_reviewer = True
                pr.create_issue_comment(
                    "Ok thank you, I will look for the next reviewer on the list :)"
                )
            if not old_reviewers:
                assign_new_reviewer = True
            if assign_new_reviewer:
                new_reviewer = next(
                    reviewer
                    for reviewer in list_of_reviewers
                    if reviewer not in old_reviewers
                )
                pr.create_issue_comment(
                    f"👋 Hi @{new_reviewer}, do you agree to review this assembly?\n"
                    "Please reply to this message only with **Yes** or **No** by"
                    f" {(current_date + timedelta(days=7)).strftime('%d-%b-%Y at %H:%M CET')}"
                )

    def assign_reviewer(self):
        try:
            comment_text = self.comment_text.lower()
            comment_author = self.comment_author.lower()
            pr = self.repo.get_pull(int(self.pr_number))
        except Exception as e:
            print(f"Missing required environment variables.\n{e}")
            sys.exit(1)
        if len(pr.requested_reviewers) > 1:
            print("The PR is already assigned to a reviewer.")
            sys.exit()
        if comment_author in map(
            str.lower, [rr.login for rr in pr.requested_reviewers]
        ):
            print("The reviewer has already been assigned.")
            sys.exit()

        comment_reviewer = None
        for comment in pr.get_issue_comments().reversed:
            text_to_check = "Please reply to this message"
            if comment.user.type == "Bot" and text_to_check in comment.body:
                comment_reviewer = re.search(r"@(\w+)", comment.body).group(1).lower()
                break
        if not comment_reviewer:
            print("Missing reviewer from the comment.")
            sys.exit(1)
        if comment_author != comment_reviewer:
            print("The reviewer is not the one who was asked to review the PR.")
            sys.exit(1)
        if "yes" in comment_text:
            supervisor = pr.assignee.login
            pr.create_review_request([comment_author])
            pr.create_issue_comment(
                f"Thank you @{comment_author} for agreeing 👍\n"
                "I appointed you as the EAR reviewer.\n"
                "Please check the [Wiki](https://github.com/ERGA-consortium/EARs/wiki/Reviewers-section)"
                " if you need to refresh something. (and remember that you must download the EAR PDF to"
                " be able to click on the link to the contact map file!)\n"
                f"Contact the PR assignee (@{supervisor}) for any issues."
            )
            pr.add_to_labels("testing")
            self.EAR_reviewer.update_reviewers_list(reviewer=comment_author, busy=True)

        elif "no" in comment_text:
            self.find_reviewer([pr], deadline_check=False)
        else:
            print("Invalid comment text.")
            sys.exit(1)

    def remove_reviewer(self):
        pr = self.repo.get_pull(int(self.pr_number))
        try:
            reviewer = self.reviewer.lower()
        except Exception as e:
            print(f"Missing required environment variables.\n{e}")
            sys.exit(1)
        supervisor = pr.assignee.login
        researcher = pr.user.login
        comment_reviewer = None
        for comment in pr.get_issue_comments().reversed:
            text_to_check = "for agreeing"
            if comment.user.type == "Bot" and text_to_check in comment.body:
                comment_reviewer = re.search(r"@(\w+)", comment.body).group(1).lower()
                break
        if comment_reviewer and comment_reviewer != reviewer:
            print("The reviewer is not the one who agreed to review the PR.")
            sys.exit(1)
        pr.create_issue_comment(
            f"Thanks @{reviewer} for the review.\nI will add a new reviewed species for you to the table when"
            f" @{supervisor} approves and merges the PR ;)\n\nCongrats on the assembly @{researcher}!\n"
            "After merging, you can [upload the assembly to ENA](https://github.com/ERGA-consortium/ERGA-submission)."
        )

    def merged_pr(self):
        pr = self.repo.get_pull(int(self.pr_number))
        reviews = pr.get_reviews()
        review = next(reversed(reviews))
        old_reviewers = []
        for comment in pr.get_issue_comments().reversed:
            text_to_check = "for the review"
            if comment.user.type == "Bot" and text_to_check in comment.body:
                comment_reviewer = re.search(r"@(\w+)", comment.body).group(1).lower()
                if any(
                    review.user.login.lower() == comment_reviewer for review in reviews
                ):
                    break

            text_to_check2 = "Please reply to this message"
            if comment.user.type == "Bot" and text_to_check2 in comment.body:
                comment_reviewer = re.search(r"@(\w+)", comment.body).group(1).lower()
                old_reviewers.append(comment_reviewer)
                break

        reviewer = review.user.login
        submitted_at = review.submitted_at.astimezone(cet).strftime("%Y-%m-%d")
        institution = re.search(r"Affiliation:\s*(\S+)", pr.body).group(1)

        self.EAR_reviewer.update_reviewers_list(
            reviewer=reviewer,
            busy=False,
            institution=institution,
            submitted_at=submitted_at,
            old_reviewers=old_reviewers,
        )
        name = next(
            entry["Full Name"]
            for entry in self.EAR_reviewer.data
            if entry["Github ID"].lower() == reviewer
        )
        species = re.search(r"Species:\s*(.+)", pr.body).group(1).strip()
        self.EAR_reviewer.add_pr(name, institution, species, pr)
        pr.remove_from_labels("testing")

    def find_supervisor(self):
        pr = self.repo.get_pull(int(self.pr_number))
        researcher = pr.user.login
        supervisor = self.EAR_reviewer.get_supervisor(researcher)
        try:
            pr.add_to_labels("ERGA-BGE")
            pr.add_to_assignees(supervisor)
            pr.create_review_request([supervisor])
            message = (
                f"👋 Hi @{researcher}, thanks for sending the EAR.\n"
                "I added the corresponding tag to the PR and appointed"
                f" @{supervisor} as the [assignee](https://github.com/ERGA-consortium/EARs/wiki/Assignees-section) to supervise."
            )
            pr.create_issue_comment(message)
        except Exception as e:
            print(f"An error occurred: {e}")
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
    group.add_argument(
        "--remove",
        action="store_true",
        help="Remove the busy reviewer from the PR.",
    )
    group.add_argument(
        "--supervisor",
        action="store_true",
        help="Find the supervisor and assign the ERGA-BGE label.",
    )
    group.add_argument(
        "--merged",
        action="store_true",
        help="Remove the testing label and update the reviewer status.",
    )
    args = parser.parse_args()
    EARBot = EARBotReviewer()
    if args.search:
        EARBot.find_reviewer()
    elif args.comment:
        EARBot.assign_reviewer()
    elif args.remove:
        EARBot.remove_reviewer()
    elif args.supervisor:
        EARBot.find_supervisor()
    elif args.merged:
        EARBot.merged_pr()
    else:
        parser.print_help()
        sys.exit(1)
