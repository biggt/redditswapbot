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


def submit_post(subreddit, post_type, month):
    """ Make the submission """
    if post_type == "price":
        title = f"OFFICIAL [PRICE CHECK] THREAD - MONTH OF {month.upper()}"
        selftext = f"""\
This is the official [Price Check] thread for /r/{subreddit}! The rules are simple:

* List what specific items you have and your questions about their value
* If you think you know what an item is worth, comment and tell the OP!
* ***OFFERING IS NOT ALLOWED***. Making offers will result in your comment being removed and a warning being issued.
* Once you're happy with the price you hear, feel free to make a trade post!
  Just make sure you follow all the rules and include a timestamped picture.

**It helps to sort by new!**"""
    elif post_type == "trade":
        title = f"{month} Confirmed Trade Thread"
        selftext = """\
Post your confirmed trades below.

When tagging an user only use standard mention (start with /u/ and add username).
Do _not_ add a link to the userpage or use any reddit formatting.

When confirming a trade please only reply with "Confirmed",
as other replies may not be accepted by the bot as a confirmation.
"""
    else:
        LOGGER.error(f"Unknown PostType: {post_type}")
        raise TypeError

    post = subreddit.submit(title, selftext=selftext, send_replies=False)
    post.mod.distinguish()
    post.mod.sticky(bottom=True)
    post.mod.suggested_sort(sort='new')
    post.mod.flair(text='Meta', css_class='meta')

    return post.id


def main():
    """ Main function """
    parser = argparse.ArgumentParser(description="Post monthly thread")
    parser.add_argument("post_type",
                        choices=["trade", "price"])
    parser.add_argument("-s", "--sidebar-only",
                        action="store_true",
                        help="Only update sidebar")
    args = parser.parse_args()

    # Setup SubRedditMod
    subreddit = SubRedditMod(LOGGER)
    month = get_month()

    # Make post
    post_type_config = subreddit.config[args.post_type]
    if not args.sidebar_only:
        post_id = submit_post(subreddit.subreddit, args.post_type, month)
    else:
        post_id = post_type_config["link_id"]

    # Update sidebar
    sidebar_link = post_type_config["sidebar_link"]
    if "sidebar_link" in post_type_config:
        subreddit.update_sidebar_link(sidebar_link, post_id)
    elif args.sidebar_only:
        LOGGER.warning("Sidebar only specified, but no sidebar link found")

    # Update config
    if "prevlink_id" in post_type_config:
        post_type_config["prevlink_id"] = post_type_config["link_id"]
    post_type_config["link_id"] = post_id
    subreddit.save_config()

    # Done
    LOGGER.info(f"Posted {args.post_type} thread")


if __name__ == "__main__":
    main()
