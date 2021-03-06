# Copyright (c) 2020 Hecong Wang
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import sqlite3 as sqlite

from .app import database, APP_DIRECTORY
from .models.assertions import Assertion, Dataset, License, Relation, Source
from .models.concepts import Concept, Language, PartOfSpeech

parser = argparse.ArgumentParser()


parser.add_argument("conceptnet", action="store", type=str,
                    help="Compiled ConceptNet assertions file (csv.gz)")
parser.add_argument("description", action="store", type=str,
                    help="Directory containing the description files (csv)")
parser.add_argument("--commit-size", action="store", type=int, default=1000,
                    help="The batch size of the database commit")

INITIALIZATION_SQL = os.path.join(APP_DIRECTORY, "initialization.sql")
TRANSFORMATION_SQL = os.path.join(APP_DIRECTORY, "transformation.sql")

ENGLISH_REGEX = re.compile(r"^/a/\[/r/.+/,/c/en/.+/,/c/en/.+/\]$")
CONCEPT_REGEX = re.compile(r"^/c/([^/]+)/([^/]+)/?([^/]+)?/?(.+)?$")

if __name__ == "__main__":
    args = parser.parse_args()

    LANGUAGE = os.path.join(args.description, "languages.csv")
    RELATION = os.path.join(args.description, "relations.csv")
    PART_OF_SPEECH = os.path.join(args.description, "part-of-speeches.csv")

    # process data using in-memory database
    with sqlite.connect(":memory:") as temp_database:
        temp_database.row_factory = sqlite.Row
        cursor = temp_database.cursor()

        with open(INITIALIZATION_SQL, "r") as script:
            cursor.executescript(script.read())
            temp_database.commit()

        with open(LANGUAGE, "r") as file:
            for language in csv.reader(file):
                cursor.execute(
                    "INSERT INTO languages(code, name) VALUES(?,?)",
                    language
                )

        with open(RELATION, "r") as file:
            for relation, directed in csv.reader(file):
                cursor.execute(
                    "INSERT INTO relations(relation, directed) VALUES(?,?)",
                    (relation, directed == "directed")
                )

        with open(PART_OF_SPEECH, "r") as file:
            for part_of_speech in csv.reader(file):
                cursor.execute(
                    "INSERT INTO part_of_speeches(code, name) VALUES(?,?)",
                    part_of_speech
                )

        temp_database.commit()

        with gzip.open(args.conceptnet, "rt") as conceptnet:
            reader = csv.reader(conceptnet, delimiter='\t')
            filtered = filter(lambda x: re.match(ENGLISH_REGEX, x[0]), reader)

            for id, assertion in enumerate(filtered):
                print(f"{id + 1} English assertions processed", end='\r')

                assertion, relation, source, target, data = assertion

                if relation == "/r/ExternalURL":
                    continue

                data = json.loads(data)

                cursor.execute(
                    "INSERT INTO assertions VALUES(" + "?," * 18 + "?)",
                    (id + 1, assertion, relation[3:],
                     source, *re.match(CONCEPT_REGEX, source).groups(),
                     target, *re.match(CONCEPT_REGEX, target).groups(),
                     data["dataset"][3:], data["license"], data["weight"],
                     data["surfaceText"] if "surfaceText" in data else None,
                     data["surfaceStart"] if "surfaceStart" in data else None,
                     data["surfaceEnd"] if "surfaceEnd" in data else None)
                )

                for index, source in enumerate(data["sources"]):
                    for field, value in source.items():
                        cursor.execute(
                            ("INSERT INTO sources"
                             "(assertion_id, [index], field, value) "
                             "VALUES(?,?,?,?)"),
                            (id + 1, index + 1, field, value)
                        )

            print()
            temp_database.commit()

        with open(TRANSFORMATION_SQL, "r") as script:
            cursor.executescript(script.read())
            temp_database.commit()

        # populate app database
        database.drop_all()
        database.create_all()

        for r in cursor.execute("SELECT * FROM languages"):
            database.session.add(Language(**r))

        for r in cursor.execute("SELECT * FROM relations"):
            database.session.add(Relation(**r))

        for r in cursor.execute("SELECT * FROM part_of_speeches"):
            database.session.add(PartOfSpeech(**r))

        for r in cursor.execute("SELECT * FROM datasets"):
            database.session.add(Dataset(**r))

        for r in cursor.execute("SELECT * FROM licenses"):
            database.session.add(License(**r))

        for i, r in enumerate(cursor.execute("SELECT * FROM concepts")):
            print(f"{i + 1} concepts inserted", end='\r')
            database.session.add(Concept(**r))

            if (i + 1) % args.commit_size == 0:
                database.session.commit()

        print()

        for i, r in enumerate(cursor.execute("SELECT * FROM assertions")):
            print(f"{i + 1} assertions inserted", end='\r')
            database.session.add(Assertion(**r))

            if (i + 1) % args.commit_size == 0:
                database.session.commit()

        print()

        for i, r in enumerate(cursor.execute("SELECT * FROM sources")):
            print(f"{i + 1} assertion source inserted", end='\r')
            database.session.add(Source(**r))

            if (i + 1) % args.commit_size == 0:
                database.session.commit()

        print()

        database.session.commit()
