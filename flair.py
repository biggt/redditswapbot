#!/usr/bin/env python3

import sys
import re
import argparse
from datetime import datetime

from log_conf import LoggerManager
from common import SubRedditMod

# Configure logging
LOGGER = LoggerManager().getLogger("trade_flair")


class TradeFlairer:
    """ Trade flair helper """

    def __init__(self, subreddit, logger):
        self._subreddit = subreddit
        self._config = subreddit.config["trade"]
        self.completed = []
        self.pending = []
        self._trade_count_cache = {}
        self._current_submission = None
        self._logger = logger

    def open_submission(self, submission):
        if submission == "curr":
            submission = self._config["link_id"]
        elif submission == "prev":
            submission = self._config["prevlink_id"]
        self._current_submission = submission

        self._logger.info("Opening trade confirmation submission {id}".format(id=submission))

        with open(submission + "_completed.log", "a+", encoding="utf-8") as completed_file:
            completed_file.seek(0)
            self.completed = completed_file.read().splitlines()

        with open(submission + "_pending.log", "a+", encoding="utf-8") as pending_file:
            pending_file.seek(0)
            self.pending = pending_file.read().splitlines()

    def close_submission(self):
        assert self._current_submission
        if self.pending:
            with open(self._current_submission + "_pending.log", "w", encoding="utf-8") as pending_file:
                pending_file.write("\n".join(self.pending))
        self._current_submission = None

    def add_completed(self, comment):
        assert self._current_submission
        self.completed.append(comment.id)
        with open(self._current_submission + "_completed.log", "a", encoding="utf-8") as completed_file:
            completed_file.write("{id}\n".format(id=comment.id))

    def add_pending(self, comment):
        assert self._current_submission
        self.pending.append(comment.id)

    def remove_pending(self, comment):
        assert self._current_submission
        self.pending.remove(comment.id)

    def get_unhandled_comments(self):
        assert self._current_submission
        comments = self._subreddit.get_top_level_comments(self._current_submission)
        handled = self.completed + self.pending
        unhandled = [comment for comment in comments if comment.id not in handled]
        self._logger.info("Checking {unhandled} out of {total} comments ({pending} pending)"
                          .format(unhandled=len(unhandled), total=len(comments),
                                  pending=len(self.pending)))
        return unhandled

    def check_top_level_comment(self, comment):
        bot_reply = self._subreddit.check_bot_reply(comment)

        explicit_link = re.search(r"\[.*\]\(.*\)", comment.body)
        match = re.findall(r"\/?u(?:ser)?\/([a-zA-Z0-9_-]+)", comment.body)

        if explicit_link or not match:
            if not bot_reply:
                comment.reply("Could not find user mention, "
                              "please edit your comment and make sure the username "
                              "starts with /u/ (no explicit linking!)")
            return None

        match = {user.lower() for user in match}
        if len(match) > 1:
            if not bot_reply:
                comment.reply("Found multiple usernames, "
                              "please only include one user per confirmation comment")
            return None

        if bot_reply:
            bot_reply.mod.remove()

        return match.pop()

    def check_reply(self, comment):
        bot_reply = self._subreddit.check_bot_reply(comment)
        if "confirmed" not in comment.body.lower():
            if not bot_reply:
                comment.reply('Could not find "confirmed" in comment, please edit your comment')
            return False

        if bot_reply:
            bot_reply.mod.remove()

        return True

    def _get_review_comment(self, comment, warning_type):
        # TODO: Move proof to config
        proofs = ["Link to screenshots of PM's between users",
                  "Link to online tracking (showing delivery) OR timestamp of received item(s)"]
        modmail_fields = [f"Comment link: {comment.permalink}"]
        modmail_fields += [f"{proof}: [REQUIRED]" for proof in proofs]
        modmail_fields += ["Please note that if any of the fields above is not filled, "
                           "your Trade Confirmation will most likely not be processed/added. "
                           "This is due to our limited moderation resources."]

        modmail_link = self._subreddit.get_modmail_link(title="Trade Confirmation Form",
                                                        subject="Trade Confirmation Proof",
                                                        content="\n\n".join(modmail_fields))
        comment_lines = [f"{self._config[warning_type]}"]
        comment_lines += [f"To verify this trade please fill out this {modmail_link}. "
                          "Please note that you need to fill out the full form "
                          "as provided with no additions or removals."]
        return "\n\n".join(comment_lines)

    def check_requirements(self, parent, reply):
        for comment in [parent, reply]:
            if self._subreddit.check_user_suspended(comment.author):
                return False
            if comment.banned_by:
                comment.report("Flair: Banned user")
                return False

            karma = comment.author.link_karma + comment.author.comment_karma
            age = (datetime.utcnow() - datetime.utcfromtimestamp(comment.author.created_utc)).days
            trade_count = self.get_author_trade_count(comment)

            if trade_count is not None and trade_count < int(self._config["flair_check"]):
                if age < int(self._config["age_check"]):
                    comment.reply(self._get_review_comment(parent, "age_warning"))
                    return False
                if karma < int(self._config["karma_check"]):
                    comment.reply(self._get_review_comment(parent, "karma_warning"))
                    return False

        return True

    def get_author_trade_count(self, item):
        if item.author.name in self._trade_count_cache:
            return self._trade_count_cache[item.author.name]
        if not item.author_flair_css_class:
            return 0

        trade_count = item.author_flair_css_class.lstrip("i-")
        try:
            trade_count = int(trade_count)
        except ValueError:
            trade_count = None
        return trade_count

    def flair(self, parent, reply, dock_trade=False):
        for comment in parent, reply:
            trade_count = self.get_author_trade_count(comment)
            if trade_count is not None:
                if dock_trade:
                    trade_count -= 1
                else:
                    trade_count += 1
                new_flair_css_class = "i-{trade_count}".format(trade_count=trade_count)
                self._subreddit.update_comment_user_flair(comment, css_class=new_flair_css_class)
                self._trade_count_cache[comment.author.name] = trade_count

        if not dock_trade:
            try:
                reply.reply(self._config["reply"])
            except Exception:
                LOGGER.info("Failed to reply, probably because of too old comment")

    def process_post(self, post):

        self.open_submission(post)

        for comment in self.get_unhandled_comments():
            if not hasattr(comment.author, 'name'):
                # Deleted comment, ignore comment and move on
                self.add_completed(comment)
                continue

            tagged_user = self.check_top_level_comment(comment)
            if tagged_user is None:
                continue

            if tagged_user.lower() == comment.author.name.lower():
                comment.report("Flair: Self-tagging")

            for reply in comment.replies:
                if not hasattr(reply.author, 'name'):
                    # Deleted comment, ignore comment and move on
                    continue
                if reply.author.name.lower() == tagged_user.lower():
                    if not self.check_reply(reply):
                        continue

                    if self.check_requirements(comment, reply):
                        self.flair(comment, reply)
                        self.add_completed(comment)
                    else:
                        self.add_pending(comment)
                    break

                reply.report("User not tagged in parent")

        self.close_submission()

    def process_mod_message(self, message):

        pattern = r"^https?:\/\/(?:www\.)?reddit\.com\/r\/.*\/comments\/.{6}\/.*\/(.{7})\/$"

        reply_lines = []
        for message_line in message.body.splitlines():
            if message_line == "":
                continue

            comment_link = re.search(pattern, message_line)
            if not comment_link:
                message.reply(f"You have submitted an invalid URL: {message_line}")
                continue

            comment_id = comment_link.group(1)
            comment = self._subreddit.praw_h.comment(id=comment_id).refresh()

            # TODO: Restore when stop supporting old confirmation threads
            # tagged_user = self.check_top_level_comment(comment)
            # if tagged_user is None:
            if "u/" not in comment.body.lower():
                message.reply(f"Could not find user mention (/u/[user]) in submitted comment: {message_line}")
                continue

            self.open_submission(comment.submission.id)

            if comment_id in self.completed:
                reply_lines += [f"Trade already completed: {message_line}"]
                continue

            # if comment_id not in self.pending:
            #     message.reply(f"Could not find trade in pending trade confirmations: {message_line}")
            #     continue

            if comment.mod_reports:
                comment.mod.approve()
            for reply in comment.replies:
                # TODO: Restore when stop supporting old confirmation threads
                # if reply.author.name.lower() == tagged_user.lower():
                if reply.author.name.lower() in comment.body.lower():
                    if not self.check_reply(reply):
                        continue
                    if reply.mod_reports:
                        reply.mod.approve()
                    self.flair(comment, reply)
                    self.add_completed(comment)
                    if comment.id in self.pending:
                        self.remove_pending(comment)
                    reply_lines += [f"Trade flair added for {comment.author.name} and {reply.author.name}: " +
                                    f"{message_line}"]
                    break
            else:
                message.reply(f"Could not find confirmation reply on submitted trade: {message_line}")
            self.close_submission()
        message.mark_read()

        return reply_lines

    def process_mod_messages(self):

        prev_message_author_name = ""
        reply_lines = []
        for message in self._subreddit.get_unread_mod_messages():
            if reply_lines and message.author.name != prev_message_author_name:
                message.reply("\n\n".join(reply_lines))
            LOGGER.info("Processing PM from mod: " + message.author.name)
            reply_lines += self.process_mod_message(message)
            prev_message_author_name = message.author.name

        if reply_lines:
            # reply_lines can only have content if at least one message
            message.reply("\n\n".join(reply_lines))  # pylint: disable=undefined-loop-variable


def main():

    parser = argparse.ArgumentParser(description="Process flairs")
    parser.add_argument("-m", dest="post", default="curr",
                        help="Which trade post to process (curr, prev or submission id)")
    parser.add_argument("-p", "--pm", dest="pm_only", default=False, action="store_true",
                        help="Only process PMs (from mods)")
    args = parser.parse_args()

    try:
        # Setup SubRedditMod
        subreddit = SubRedditMod(LOGGER)

        # Setup tradeflairer
        trade_flairer = TradeFlairer(subreddit, LOGGER)

        if not args.pm_only:
            trade_flairer.process_post(args.post)

        trade_flairer.process_mod_messages()

    except KeyboardInterrupt:
        print("\nCtrl-C pressed, exiting gracefully")
        sys.exit()

    except Exception as exception:
        LOGGER.error(exception)
        sys.exit()


if __name__ == '__main__':
    main()
