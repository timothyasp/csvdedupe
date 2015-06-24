import os
import csv
import re
import collections
import logging
from cStringIO import StringIO
import sys
from signal import signal, SIGPIPE, SIG_DFL
signal(SIGPIPE, SIG_DFL)

import AsciiDammit
import dedupe
import json
import argparse

def preProcess(column):
    """
    Do a little bit of data cleaning with the help of
    [AsciiDammit](https://github.com/tnajdek/ASCII--Dammit) and
    Regex. Things like casing, extra spaces, quotes and new lines can
    be ignored.
    """
    column = AsciiDammit.asciiDammit(column)
    column = re.sub('  +', ' ', column)
    column = re.sub('\n', ' ', column)
    column = column.strip().strip('"').strip("'").lower().strip()
    return column


def readData(input_file, field_names, prefix=None):
    """
    Read in our data from a CSV file and create a dictionary of records,
    where the key is a unique record ID and each value is a
    [frozendict](http://code.activestate.com/recipes/414283-frozen-dictionaries/)
    (hashable dictionary) of the row fields.

    **Currently, dedupe depends upon records' unique ids being integers
    with no integers skipped. The smallest valued unique id must be 0 or
    1. Expect this requirement will likely be relaxed in the future.**
    """

    data = {}
    reader = csv.DictReader(StringIO(input_file))
    for i, row in enumerate(reader):
        clean_row = [(k, preProcess(v)) for (k, v) in row.items()]
        if prefix:
            row_id = "%s|%s" % (prefix, i)
        else:
            row_id = i
        data[row_id] = dedupe.core.frozendict(clean_row)

    return data


# ## Writing results
def writeResults(clustered_dupes, input_file, output_file):

    # Write our original data back out to a CSV with a new column called
    # 'Cluster ID' which indicates which records refer to each other.

    logging.info('saving results to: %s' % output_file)

    cluster_membership = {}
    for cluster_id, (cluster, score) in enumerate(clustered_dupes):
        ndx = 0
        for record_id in cluster:
            cluster_membership[record_id] = [cluster_id, score[ndx]]
            ndx += 1

    unique_record_id = cluster_id + 1

    writer = csv.writer(output_file)

    reader = csv.reader(StringIO(input_file))

    heading_row = reader.next()
    heading_row.insert(0, 'Cluster ID')
    heading_row.insert(1, 'Confidence Score')
    writer.writerow(heading_row)

    for row_id, row in enumerate(reader):
        if row_id in cluster_membership:
            cluster_id = cluster_membership[row_id][0]
            score = cluster_membership[row_id][1]
        else:
            score = 1
            cluster_id = unique_record_id
            unique_record_id += 1
        row.insert(0, cluster_id)
        row.insert(1, score)
        writer.writerow(row)


# ## Writing results
def writeUniqueResults(clustered_dupes, input_file, output_file):

    # Write our original data back out to a CSV with a new column called
    # 'Cluster ID' which indicates which records refer to each other.

    logging.info('saving unique results to: %s' % output_file)

    cluster_membership = {}
    for (cluster_id, cluster) in enumerate(clustered_dupes):
        for record_id in cluster:
            cluster_membership[record_id] = cluster_id

    unique_record_id = cluster_id + 1

    writer = csv.writer(output_file)

    reader = csv.reader(StringIO(input_file))

    heading_row = reader.next()
    heading_row.insert(0, 'Cluster ID')
    writer.writerow(heading_row)

    seen_clusters = set()
    for row_id, row in enumerate(reader):
        if row_id in cluster_membership:
            cluster_id = cluster_membership[row_id]
            if cluster_id not in seen_clusters:
                row.insert(0, cluster_id)
                writer.writerow(row)
                seen_clusters.add(cluster_id)
        else:
            cluster_id = unique_record_id
            unique_record_id += 1
            row.insert(0, cluster_id)
            writer.writerow(row)


def writeLinkedResults(clustered_pairs, input_1, input_2, output_file,
                       inner_join=False):
    logging.info('saving unique results to: %s' % output_file)

    matched_records = []
    seen_1 = set()
    seen_2 = set()

    input_1 = [row for row in csv.reader(StringIO(input_1))]
    row_header = input_1.pop(0)
    length_1 = len(row_header)

    input_2 = [row for row in csv.reader(StringIO(input_2))]
    row_header_2 = input_2.pop(0)
    length_2 = len(row_header_2)
    row_header += row_header_2

    for pair in clustered_pairs:
        index_1, index_2 = [int(index.split('|', 1)[1]) for index in pair[0]]

        matched_records.append(input_1[index_1] + input_2[index_2])
        seen_1.add(index_1)
        seen_2.add(index_2)

    writer = csv.writer(output_file)
    writer.writerow(row_header)

    for matches in matched_records:
        writer.writerow(matches)

    if not inner_join:

        for i, row in enumerate(input_1):
            if i not in seen_1:
                writer.writerow(row + [None] * length_2)

        for i, row in enumerate(input_2):
            if i not in seen_2:
                writer.writerow([None] * length_1 + row)

class CSVCommand(object) :
    def __init__(self) :
        self.parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        self._common_args()
        self.add_args()

        self.args = self.parser.parse_args()

        self.configuration = {}

        if self.args.config_file:
            #read from configuration file
            try:
                with open(self.args.config_file, 'r') as f:
                    config = json.load(f)
                    self.configuration.update(config)
            except IOError:
                raise self.parser.error(
                    "Could not find config file %s. Did you name it correctly?"
                    % self.args.config_file)

        # override if provided from the command line
        args_d = vars(self.args)
        args_d = dict((k, v) for (k, v) in args_d.items() if v is not None)
        self.configuration.update(args_d)

        self.output_file = self.configuration.get('output_file', None)
        self.skip_training = self.configuration.get('skip_training', False)
        self.training_file = self.configuration.get('training_file',
                                               'training.json')
        self.sample_size = self.configuration.get('sample_size', 1500)
        self.recall_weight = self.configuration.get('recall_weight', 2)

        if 'field_definition' in self.configuration:
            self.field_definition = self.configuration['field_definition']
        else :
            self.field_definition = None


    def _common_args(self) :
        # optional arguments
        self.parser.add_argument('--config_file', type=str,
            help='Path to configuration file. Must provide either a config_file or input and field_names.')
        self.parser.add_argument('--field_names', type=str, nargs="+",
            help='List of column names for dedupe to pay attention to')
        self.parser.add_argument('--output_file', type=str,
            help='CSV file to store deduplication results')
        self.parser.add_argument('--skip_training', action='store_true',
            help='Skip labeling examples by user and read training from training_file only')
        self.parser.add_argument('--training_file', type=str,
            help='Path to a new or existing file consisting of labeled training examples')
        self.parser.add_argument('--sample_size', type=int,
            help='Number of random sample pairs to train off of')
        self.parser.add_argument('--recall_weight', type=int,
            help='Threshold that will maximize a weighted average of our precision and recall')
        self.parser.add_argument('-v', '--verbose', action='count', default=0)

