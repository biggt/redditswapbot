#!/usr/bin/env python3
""" New post checker """

import sys
import re
import sqlite3
import unicodedata
import json
import os
import math
from datetime import datetime
from time import sleep

from log_conf import LoggerManager
from common import SubRedditMod


# configure logging
LOGGER = LoggerManager().getLogger("post_check")


class PostChecker:
    """ Post check helper """

    def __init__(self, subreddit, db_con, post_categories, locations):
        self._subreddit = subreddit
        self._config = subreddit.config["post_check"]
        self._user_db_con = db_con
        self._user_db_cursor = self._user_db_con.cursor()
        self._post_categories = post_categories
        self._locations = locations

    def _get_user_db_entry(self, post):
        self._user_db_cursor.execute('SELECT * FROM user WHERE username=?', (post.author.name,))
        return self._user_db_cursor.fetchone()

    def _update_user_db(self, post, fields_to_set):
        fields = ", ".join(field + "=?" for field in fields_to_set)
        self._user_db_cursor.execute('UPDATE OR IGNORE user SET {} WHERE username=?'.format(fields),
                                     (post.created_utc, post.id, post.author.name))

    def _add_to_user_db(self, post, fields_to_set):
        fields = ", ".join(("username",) + fields_to_set)
        self._user_db_cursor.execute('INSERT OR IGNORE INTO user ({}) VALUES (?, ?, ?)'.format(fields),
                                     (post.author.name, post.created_utc, post.id))

    def _is_personal_post(self, title):
        return bool(re.search(self._config["trade_post_format"], title))

    def _is_informational_post(self, title):
        return bool(re.search(self._config["informational_post_format"], title))

    def save_submission(self, post):
        user_path = os.path.join(self._config["user_history_dir"], str(post.author))

        if not os.path.exists(user_path):
            os.makedirs(user_path)

        with open(os.path.join(user_path, post.id), "w", encoding="utf-8") as submission_file:
            submission_file.write(unicodedata.normalize('NFKD', post.title).encode('ascii', 'ignore').decode() + "\n")
            submission_file.write(unicodedata.normalize('NFKD', post.selftext).encode('ascii', 'ignore').decode())

    def check_and_flair_personal(self, post, clean_title):
        """ Check title of personal post and flair accordingly """

        location, have, want = re.search(self._config["trade_post_format"], clean_title).groups()

        if "-" in location:
            primary, secondary = location.split("-", 1)
        else:
            primary = "OTHER"
            secondary = location

        if (primary not in self._locations or
                secondary not in self._locations[primary]):
            self.remove_post(post, "location")
            return False

        if self._config["user_history_dir"]:
            self.save_submission(post)

        timestamp_check = False
        post_flair = self._config["default_category"]
        flairs = self._post_categories["flairs"]
        for flair, flair_prop in flairs.items():
            assert not ("have" in flair_prop and "want" in flair_prop), "Limitation of script"
            if "want" in flair_prop:
                regex = flair_prop["want"].replace("\\\\", "\\")
                if re.search(regex, want, re.IGNORECASE):
                    post_flair = flair
                    timestamp_check = flair_prop["timestamp_check"]
            if "have" in flair_prop:
                regex = flair_prop["have"].replace("\\\\", "\\")
                if re.search(regex, have, re.IGNORECASE):
                    post_flair = flair
                    timestamp_check = flair_prop["timestamp_check"]

        post.mod.flair(text=post_flair, css_class=flairs[post_flair]["class"])

        self.check_repost(post, flairs[post_flair].get("group", "personal"))

        if timestamp_check:
            lines = list(line for line in post.selftext.splitlines() if line)
            if not re.search(self._config["timestamp_regex"], post.selftext, re.IGNORECASE):
                post.report("Could not find timestamp.")
            if not re.search(self._config["timestamp_regex"], " ".join(lines[:3]), re.IGNORECASE):
                post.reply("Hello, we have updated the rules with a recommendation to include the "
                           "timestamp at the beginning of the submission and I could not find any "
                           "timestamp in the beginning of your submission.\n\n"
                           "(If this is not true, for example if this is a 'Buying' submission, "
                           "you can ignore this comment)")

        self.post_comment(post)

        return True

    def check_and_flair_informational(self, post, clean_title):
        """ Check title of informational post and flair accordingly """

        tag = re.search(self._config["informational_post_format"], clean_title).group(1)

        for category, category_prop in self._post_categories["flairs"].items():
            if tag == category_prop.get("tag", None):
                post_flair = category
                post_flair_prop = category_prop
                break
        else:
            self.remove_post(post, "tag")
            return False

        post.mod.flair(text=post_flair, css_class=post_flair_prop["class"])

        if "required_flair" in post_flair_prop:
            if post_flair_prop["required_flair"] != post.author_flair_css_class:
                # TODO: Remove from automod and add reply here
                pass

        self.check_repost(post, post_flair_prop.get("group", "nonpersonal"))

        if post_flair_prop.get("reply", True):
            self.post_comment(post)

        return True

    def check_post(self, post):
        """
        Check post for rule violations
        """

        clean_title = unicodedata.normalize('NFKD', post.title).encode('ascii', 'ignore').decode()

        if self._is_personal_post(clean_title):
            if "trade_post_format_strict" in self._config:
                if not bool(re.match(self._config["trade_post_format_strict"], clean_title)):
                    self.remove_post(post, "title")
                    return

            if not self.check_and_flair_personal(post, clean_title):
                return

        elif self._is_informational_post(clean_title):
            # TODO: Add strict format check (not necessary at the moment)
            if not self.check_and_flair_informational(post, clean_title):
                return

        else:
            self.remove_post(post)
            return

    def remove_post(self, post, bad_part="title"):
        """
        Reply and remove post
        """

        # TODO: Implement this in a better way
        if post.author in self._subreddit.get_mods():
            # Let mods make posts with arbitrary tags
            return

        comment = "REMOVED: Your post was automatically removed due to an incorrect title."
        comment += "\n\nYour **{bad_part}** does not match the format specified in the {rules_link}.".format(
            bad_part=bad_part, rules_link=self._subreddit.get_rules_link())
        post.reply(comment).mod.distinguish()
        post.mod.remove()

    def post_comment(self, post):
        """
        Post user info comment
        """

        try:
            reputation = int(post.author_flair_css_class.lstrip('i-'))
        except AttributeError:
            reputation = 0
        except ValueError:
            reputation = post.author_flair_css_class.lstrip('i-')

        comment_lines = []
        comment_lines += [f"* Submission time: {datetime.utcfromtimestamp(post.created_utc)} UTC"]
        comment_lines += ["  * [[Click here to see current UTC time]]" +
                          "(https://time.is/UTC)"]
        comment_lines += [f"* Username: /u/{post.author.name}"]
        comment_lines += ["  * [[Click here to send a PM to this user]]" +
                          f"(https://www.reddit.com/message/compose/?to={post.author.name})"]
        comment_lines += [f"* Join date: {datetime.utcfromtimestamp(post.author.created_utc)}"]
        comment_lines += [f"* Link karma: {post.author.link_karma}"]
        comment_lines += [f"* Comment karma: {post.author.comment_karma}"]
        if isinstance(reputation, int):
            comment_lines += [f"* Reputation: {reputation} trade(s)"]
        else:
            comment_lines += [f"* Reputation: User is currently a {reputation}."]
        # TODO: Distinguish between normal flair and other flairs
        if post.author_flair_text is not None and "http" in post.author_flair_text:
            name = "Heatware" if "heatware" in post.author_flair_text else "Link"
            comment_lines += [f"* {name}: [{post.author_flair_text}]({post.author_flair_text})"]
        disclaimer = ("This information does not guarantee a successful swap. "
                      "It is being provided to help potential trade partners have "
                      "more immediate background information about with whom they are swapping. "
                      "Please be sure to familiarize yourself with the "
                      "{rules} and other guides on the {wiki}").format(
                          rules=self._subreddit.get_rules_link(), wiki=self._subreddit.get_wiki_link())
        disclaimer = "\n^^" + disclaimer.replace(" ", " ^^")
        comment_lines += [disclaimer]
        post.reply("\n".join(comment_lines)).mod.distinguish()

    def check_repost(self, post, group):
        """
        Check post for repost rule violations
        """

        cooldown = self._post_categories["groups"][group].get("cooldown", None)
        if cooldown is None:
            return

        db_row = self._get_user_db_entry(post)
        last_created_col = "{}_last_created".format(group)
        last_id_col = "{}_last_id".format(group)
        if db_row is not None:
            last_id = db_row[last_id_col]
            last_created = db_row[last_created_col]
            if post.id != last_id:
                LOGGER.info("Checking post {} for repost violation".format(post.id))
                post_created = post.created_utc
                seconds_between_posts = (post_created - last_created)
                if (seconds_between_posts < int(self._config["lower_min"]) * 60 and
                        self._subreddit.is_removed(last_id)):
                    LOGGER.info("Submission https://redd.it/{} not reported because grace period. "
                                "(Previous submission: https://redd.it/{})".format(post.id, last_id))
                elif seconds_between_posts < cooldown * 3600:
                    LOGGER.info("Submission https://redd.it/{} removed and flagged for repost violation. "
                                "(Previous submission: https://redd.it/{})".format(post.id, last_id))
                    post.mod.remove()
                    # Add an extra hour for good measure
                    remaining_hours = math.ceil(cooldown - seconds_between_posts / 3600) + 1
                    reply = post.reply(("Your submission has automatically been removed violating the " +
                                        "cooldown period for {group} submissions. " +
                                        "You will need to wait at least another {hours} hours " +
                                        "before submitting a new submission.\n\n" +
                                        "Note that repeated violations of this rule can result in a temporary " +
                                        "suspension, so please keep track of your submission times in the future.\n\n" +
                                        "For more information regarding the general posting rules, such as " +
                                        "cooldowns, please read the {rules}.\n\n" +
                                        "If you think this removal was made in error, please send a {modmail}.").format(
                                            group=group, hours=remaining_hours,
                                            rules=self._subreddit.get_rules_link("rules"),
                                            modmail=self._subreddit.get_modmail_link()))
                    reply.report("Repost, link to previous post: https://redd.it/{}".format(last_id))
                    return
            self._update_user_db(post, (last_created_col, last_id_col))
        else:
            self._add_to_user_db(post, (last_created_col, last_id_col))

        self._user_db_con.commit()


def main():
    """ Main function, setups stuff and checks posts"""

    try:
        # Setup SubRedditMod
        subreddit = SubRedditMod(LOGGER)
        with open("submission_categories.json", "r", encoding="utf-8") as category_file:
            post_categories = json.load(category_file)
        with open("locations.json", "r", encoding="utf-8") as locations_file:
            locations = json.load(locations_file)

        # Setup PostChecker
        user_db = subreddit.config["trade"]["user_db"]
        db_con = sqlite3.connect(user_db)
        db_con.row_factory = sqlite3.Row
        post_checker = PostChecker(subreddit, db_con, post_categories, locations)
    except Exception as exception:
        LOGGER.error(exception)
        sys.exit()

    while True:
        try:
            first_pass = True
            processed = []
            while True:
                new_posts = subreddit.get_new(50)
                for post in new_posts:
                    if first_pass and subreddit.check_mod_reply(post, exclude_mods=["AutoModerator"]):
                        processed.append(post.id)
                    if post.id in processed:
                        continue
                    post_checker.check_post(post)
                    processed.append(post.id)
                first_pass = False
                LOGGER.debug("Sleeping for 1 minute")
                sleep(60)

        except KeyboardInterrupt:
            print("\nCtrl-C pressed, exiting gracefully")
            sys.exit(0)

        except Exception as exception:
            LOGGER.error(exception)
            sleep(60)


if __name__ == '__main__':
    main()
