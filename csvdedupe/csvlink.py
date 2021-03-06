#! /usr/bin/env python

import logging
import os
import sys
import json
from cStringIO import StringIO

import csvhelpers
import dedupe

import itertools

class CSVLink(csvhelpers.CSVCommand):
    def __init__(self):
        super(CSVLink, self).__init__()

        if len(self.configuration['input']) == 2:
            try:
                self.input_1 = open(self.configuration['input'][0], 'rU').read()
            except IOError:
                raise self.parser.error("Could not find the file %s" %
                                   (self.configuration['input'][0], ))

            try:
                self.input_2 = open(self.configuration['input'][1], 'rU').read()
            except IOError:
                raise self.parser.error("Could not find the file %s" %
                                   (self.configuration['input'][1], ))

        else:
            raise self.parser.error("You must provide two input files.")

        if 'field_names' in self.configuration:
            if 'field_names_1' in self.configuration or 'field_names_2' in self.configuration:
                raise self.parser.error(
                    "You should only define field_names or individual dataset fields (field_names_1 and field_names_2")
            else:
                self.field_names_1 = self.configuration['field_names']
                self.field_names_2 = self.configuration['field_names']
        elif 'field_names_1' in self.configuration and 'field_names_2' in self.configuration:
            self.field_names_1 = self.configuration['field_names_1']
            self.field_names_2 = self.configuration['field_names_2']
        else:
            raise self.parser.error(
                "You must provide field_names of field_names_1 and field_names_2")

        self.inner_join = self.configuration.get('inner_join', False)

        if self.field_definition is None :
            self.field_definition = [{'field': field,
                                      'type': 'String'}
                                     for field in self.field_names_1]

    def add_args(self) :
        # positional arguments
        self.parser.add_argument('input', nargs="+", type=str,
            help='The two CSV files to operate on.')
        self.parser.add_argument('--field_names_1', type=str, nargs="+",
            help='List of column names for first dataset')
        self.parser.add_argument('--field_names_2', type=str, nargs="+",
            help='List of column names for second dataset')
        self.parser.add_argument('--inner_join', action='store_true',
            help='Only return matches between datasets')

    def main(self):

        data_1 = {}
        data_2 = {}
        # import the specified CSV file

        data_1 = csvhelpers.readData(self.input_1, self.field_names_1,
                                     prefix='input_1')
        data_2 = csvhelpers.readData(self.input_2, self.field_names_2,
                                     prefix='input_2')

        # sanity check for provided field names in CSV file
        for field in self.field_names_1:
            if field not in data_1.values()[0]:
                raise self.parser.error(
                    "Could not find field '" + field + "' in input")

        for field in self.field_names_2:
            if field not in data_2.values()[0]:
                raise self.parser.error(
                    "Could not find field '" + field + "' in input")

        if self.field_names_1 != self.field_names_2:
            for record_id, record in data_2.items():
                remapped_record = {}
                for new_field, old_field in zip(self.field_names_1,
                                                self.field_names_2):
                    remapped_record[new_field] = record[old_field]
                data_2[record_id] = remapped_record

        logging.info('imported %d rows from file 1', len(data_1))
        logging.info('imported %d rows from file 2', len(data_2))

        logging.info('using fields: %s' % [field['field']
                                           for field in self.field_definition])
        # # Create a new deduper object and pass our data model to it.
        deduper = dedupe.RecordLink(self.field_definition)

        # Set up our data sample
        logging.info('taking a sample of %d possible pairs', self.sample_size)
        deduper.sample(data_1, data_2, self.sample_size)

        # If we have training data saved from a previous run of dedupe,
        # look for it an load it in.
        # __Note:__ if you want to train from scratch, delete the training_file

        if os.path.exists(self.training_file):
            logging.info('reading labeled examples from %s' %
                         self.training_file)
            with open(self.training_file) as tf:
                deduper.readTraining(tf)
        elif self.skip_training:
            raise self.parser.error(
                "You need to provide an existing training_file or run this script without --skip_training")

        if not self.skip_training:
            logging.info('starting active labeling...')

            dedupe.consoleLabel(deduper)

            # When finished, save our training away to disk
            logging.info('saving training data to %s' % self.training_file)
            with open(self.training_file, 'w') as tf:
                deduper.writeTraining(tf)
        else:
            logging.info('skipping the training step')

        deduper.train()

        # ## Blocking

        logging.info('blocking...')

        # ## Clustering

        # Find the threshold that will maximize a weighted average of our precision and recall. 
        # When we set the recall weight to 2, we are saying we care twice as much
        # about recall as we do precision.
        #
        # If we had more data, we would not pass in all the blocked data into
        # this function but a representative sample.

        logging.info('finding a good threshold with a recall_weight of %s' %
                     self.recall_weight)
        threshold = deduper.threshold(data_1, data_2,
                                      recall_weight=self.recall_weight)

        # `duplicateClusters` will return sets of record IDs that dedupe
        # believes are all referring to the same entity.

        logging.info('clustering...')
        clustered_dupes = deduper.match(data_1, data_2, threshold)

        logging.info('# duplicate sets %s' % len(clustered_dupes))

        write_function = csvhelpers.writeLinkedResults
        # write out our results

        if self.output_file:
            with open(self.output_file, 'w') as output_file:
                write_function(clustered_dupes, self.input_1, self.input_2,
                               output_file, self.inner_join)
        else:
            write_function(clustered_dupes, self.input_1, self.input_2,
                           sys.stdout, self.inner_join)


def launch_new_instance():
    d = CSVLink()
    d.main()

if __name__ == "__main__":
    launch_new_instance()
