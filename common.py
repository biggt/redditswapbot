""" Common stuff """

import sys
import os
import urllib
import re

from configparser import SafeConfigParser

import praw
from praw.models.reddit import widgets
import puni


# TODO: Split into one generic helper class and one with mod specific actions
class SubRedditMod:  # pylint: disable=too-many-public-methods
    """ Helper class to mod a subreddit """

    _mods = None
    _suspended = {}
    _removed = {}

    def __init__(self, logger):
        self.logger = logger
        self.config = self._load_config()
        self._sub_config = self.config["subreddit"]
        self.praw_h = self.login()
        self.subreddit = self.praw_h.subreddit(self._sub_config["uri"])
        self.puni_h = puni.UserNotes(self.praw_h, self.subreddit)

    @property
    def subreddit_uri(self):
        return "/r/" + self._sub_config["uri"]

    @property
    def username(self):
        return self.config["login"]["username"]

    def get_usernotes(self, username):
        return self.puni_h.get_notes(username)

    def set_usernote(self, user, reason, link='', warning='none'):
        note = puni.Note(user, reason, self._sub_config["uri"], self.username, link, warning)
        self.puni_h.add_note(note)

    def get_rules_link(self, title="RULES"):
        return "[{title}]({uri})".format(
            title=title, uri=self.subreddit_uri + self._sub_config["rules"])

    def get_wiki_link(self, title="WIKI"):
        return "[{title}]({uri})".format(
            title=title, uri=self.subreddit_uri + self._sub_config["wiki"])

    @staticmethod
    def _load_config():
        """ Load config from config.cfg """
        containing_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
        path_to_cfg = os.path.join(containing_dir, 'config.cfg')
        config = SafeConfigParser()
        config.read(path_to_cfg)
        return config

    def save_config(self):
        """ Save config to config.cfg """
        containing_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
        path_to_cfg = os.path.join(containing_dir, 'config.cfg')
        with open(path_to_cfg, "w", encoding="utf-8") as configfile:
            self.config.write(configfile)

    def login(self):
        """ Login in praw """
        login_info = self.config["login"]
        self.logger.info('Logging in as /u/' + login_info["username"])
        return praw.Reddit(**login_info)

    def get_modmail_link(self, title="modmail", subject=None, content=None):
        """ Get link to modmail """
        link = ("https://www.reddit.com/message/compose?to={subreddit}"
                .format(subreddit=self.subreddit_uri))
        if subject:
            link += "&subject=" + urllib.parse.quote_plus(subject)
        if content:
            link += "&message=" + urllib.parse.quote_plus(content)
        return "[{title}]({link})".format(title=title, link=link)

    def get_unread_messages(self):
        """ Get unread messages (not comment replies) """
        return [msg for msg in self.praw_h.inbox.unread(limit=100) if not msg.was_comment]

    def get_unread_mod_messages(self):
        """ Get undread messages from mods """
        return [msg for msg in self.get_unread_messages() if msg.author in self.get_mods()]

    def is_removed(self, submission_id):
        """ Returns if the submission with submission_id is removed (by mod or user) """
        if submission_id in self._removed:
            return self._removed[submission_id]

        submission = self.praw_h.submission(id=submission_id)
        removed = submission.removed or (submission.author is None)
        self._removed[submission_id] = removed
        return removed

    def get_top_level_comments(self, link_id):
        """ Get all top level comments on a submission with specified link_id """
        submission = self.praw_h.submission(id=link_id)
        submission.comments.replace_more(limit=None, threshold=0)
        return submission.comments

    def get_all_comments(self, link_id):
        """ Get all comments on a submission with specified link_id """
        return self.get_top_level_comments(link_id).list()

    def update_comment_user_flair(self, comment, css_class=None, text=None):
        """ Update the user flair of an author of a comment """
        if css_class is None:
            css_class = comment.author_flair_css_class
        else:
            self.logger.info("Set {}'s flair class to {}".format(comment.author.name, css_class))
        if text is None:
            text = comment.author_flair_text
        else:
            self.logger.info("Set {}'s flair text to {}".format(comment.author.name, text))
        self.subreddit.flair.set(comment.author, text, css_class)

    def get_new(self, limit=20):
        """ Get new posts """
        return self.subreddit.new(limit=limit)

    @staticmethod
    def _get_replies(item):
        """ Get replies to submission or comment """
        if isinstance(item, praw.models.reddit.submission.Submission):
            comments = item.comments
        elif isinstance(item, praw.models.reddit.comment.Comment):
            comments = item.replies
        else:
            raise TypeError("Unknown item type {}".format(type(item)))
        return comments

    def get_mods(self):
        """ Cache mods """
        if self._mods is None:
            self._mods = self.subreddit.moderator()
        return self._mods

    def check_mod_reply(self, item):
        """ Check if mod already has replied """
        comments = self._get_replies(item)

        for comment in comments:
            if comment.author in self.get_mods():
                return True
        return False

    def check_bot_reply(self, item):
        """ Check if bot has replied, if so return comment """
        comments = self._get_replies(item)

        for comment in comments:
            if comment.author == self.username:
                return comment
        return None

    def check_user_suspended(self, user):
        """ Check if user is suspended/shadowbanned """
        if user.name in self._suspended:
            return self._suspended[user.name]

        if hasattr(user, 'fullname'):
            self._suspended[user.name] = False
            return False

        self._suspended[user.name] = True
        return True

    def update_sidebar_link(self, post_text, post_id):
        """ Update sidebar links """

        # Old reddit
        sidebar = self.subreddit.wiki["config/sidebar"]
        new_link = fr'[{post_text}](/{post_id})'
        new_md = re.sub(fr'\[{post_text}\]\(\/[a-z0-9]+\)', new_link, sidebar.content_md, 1)
        sidebar.edit(content=new_md)

        # New reddit
        for widget in self.subreddit.widgets.items.values():
            if (isinstance(widget, widgets.ButtonWidget) and
                    widget.shortName == "Links"):
                buttons = widget.buttons
                for button in buttons:
                    if button.text == post_text:
                        button.url = f"https://redd.it/{post_id}"
                widget.mod.update(buttons=buttons)
