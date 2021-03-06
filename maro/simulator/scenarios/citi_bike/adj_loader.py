# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import csv


def load_adj_from_csv(file: str, skiprows: int = 0):
    """Read adj information from csv file"""
    adj = []
    if file.startswith("~"):
        file = os.path.expanduser(file)
    with open(file, "rt") as fp:
        reader = csv.reader(fp)

        for row in reader:
            # skip rows
            if skiprows > 0:
                skiprows -= 1
                continue

            adj.append([float(col) for col in row])

    return adj