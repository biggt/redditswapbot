#!/usr/bin/env python3
""" Script to make monthly scheduled submissions and update links """

import argparse
import time

from log_conf import LoggerManager
from common import SubRedditMod

# Configure logging
LOGGER = LoggerManager().getLogger("monthly_post")


def get_month():
    month = time.strftime('%B')
    return month


def submit_post(subreddit, month):
    """ Make the submission """
    title = f"OFFICIAL [PRICE CHECK] THREAD - MONTH OF {month.upper()}"
    selftext = f"""\
This is the official [Price Check] thread for /r/{subreddit}! The rules are simple:

* List what specific items you have and your questions about their value
* If you think you know what an item is worth, comment and tell the OP!
* ***OFFERING IS NOT ALLOWED***. Making offers will result in your comment being removed and a warning being issued.
* Once you're happy with the price you hear, feel free to make a trade post!
  Just make sure you follow all the rules and include a timestamped picture.

**It helps to sort by new!**"""

    post = subreddit.submit(title, selftext=selftext, send_replies=False)
    post.mod.distinguish()
    post.mod.sticky(bottom=True)
    post.mod.suggested_sort(sort='new')
    post.mod.flair(text='Meta', css_class='meta')

    return post.id


def main():
    """ Main function """
    parser = argparse.ArgumentParser(description="Post montly thread")
    parser.add_argument("-s", "--sidebar-only",
                        action="store_true",
                        help="Only update sidebar")
    args = parser.parse_args()

    # Setup SubRedditMod
    subreddit = SubRedditMod(LOGGER)
    month = get_month()

    if args.sidebar_only:
        post_id = subreddit.config.get('price', 'link_id')
    else:
        post_id = submit_post(subreddit.subreddit, month)
    subreddit.update_sidebar_link("Price check thread", post_id)
    subreddit.config.set('price', 'link_id', post_id)
    subreddit.save_config()
    LOGGER.info("Posted Price Check thread")


if __name__ == '__main__':
    main()
