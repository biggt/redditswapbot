#!/usr/bin/env python2

import sys, os
import json
import argparse
import sqlite3 as lite

con = None

def extant_file(x):
    if not os.path.exists(x):
        raise argparse.ArgumentError("{0} does not exist".format(x))
    return x

def main():
    # parser = argparse.ArgumentParser(description="Import flairs")
    # parser.add_argument("-f", "--file", dest="filename", help="json input file", metavar="FILE", type=extant_file, required=True)
    # args = parser.parse_args()

    try:
        old_con = lite.connect('old_user.db', detect_types=lite.PARSE_DECLTYPES | lite.PARSE_COLNAMES)
        old_con.row_factory = lite.Row
        new_con = lite.connect('new_user.db')
    except lite.Error as e:
        print("Error %s:" % e.args[0])
        sys.exit(1)

    old_curs = old_con.cursor()
    new_curs = new_con.cursor()

    new_curs.execute('''CREATE TABLE IF NOT EXISTS user (
username TEXT PRIMARY KEY NOT NULL ,
flair_text TEXT,
flair_css_class TEXT,
personal_last_created INTEGER DEFAULT 0,
personal_last_id TEXT DEFAULT '',
nonpersonal_last_created INTEGER DEFAULT 0,
nonpersonal_last_id TEXT DEFAULT ''
)''')

    old_curs.execute('SELECT username, last_id, last_created as "last_created [timestamp]" FROM user')
    results = old_curs.fetchall()

    import pdb
    new_lines = []
    # pdb.set_trace()
    for line in results:
        new_lines.append((line[0], line[1], int(line[2].strftime("%s"))+2*60*60))

    # pdb.set_trace()

    new_curs.executemany('INSERT INTO user (username, personal_last_id, personal_last_created) VALUES (:user, :personal_last_id, :personal_last_created)', new_lines)

    new_con.commit()

    if new_con:
        new_con.close()

if __name__ == "__main__":
    main()
