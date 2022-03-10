import pytest, pathlib

import gpas_uploader

def test_no_upload_csv_fails():

    with pytest.raises(Exception) as e_info:
        validate.Batch('tests/files/none-existent-file.csv')

def test_illumina_bam_pass_1():

    a = gpas_uploader.Batch('tests/files/illumina-bam-upload-csv-pass-1.csv')

    # this spreadsheet is valid
    assert a.valid


def test_nanopore_bam_pass_1():

    a = gpas_uploader.Batch('tests/files/nanopore-bam-upload-csv-pass-1.csv')

    # this spreadsheet is valid
    assert a.valid

def test_illumina_bam_instrument_notunique():

    a = gpas_uploader.Batch('tests/files/illumina-bam-upload-csv-fail-1.csv')

    # this spreadsheet is not valid
    assert not a.valid

    # there is only a single error
    assert len(a.errors) == 1



def test_illumina_bam_files_donotexist():

    a = gpas_uploader.Batch('tests/files/illumina-bam-upload-csv-fail-2.csv')

    # this spreadsheet is not valid
    assert not a.valid

    # there is only a single error
    assert len(a.errors) == 1

    # which is that one of the bam files does not exist
    assert list(a.errors.error_message) == ['bam does not exist']


def test_nanopore_bam_check_fails_1():

    a = gpas_uploader.Batch('tests/files/nanopore-bam-upload-csv-fail-1.csv')

    # this spreadsheet is not valid!
    assert not a.valid

    # there should be 11 different errors
    assert len(a.errors) == 13

    # two of the errors apply to the whole sheet
    assert len(a.errors[a.errors.index.isna()]) == 2


def test_illumina_fastq_pass_1():

    a = gpas_uploader.Batch('tests/files/illumina-fastq-upload-csv-pass-1.csv')

    # this spreadsheet is valid
    assert a.valid


# check an upload CSV where the run_number is null
def test_illumina_fastq_pass_2():

    a = gpas_uploader.Batch('tests/files/illumina-fastq-upload-csv-pass-2.csv')

    # this spreadsheet is valid
    assert a.valid


# check an upload CSV where batch is incorrectly called batch_name
def test_illumina_fastq_pass_2():

    a = gpas_uploader.Batch('tests/files/illumina-fastq-upload-csv-fail-1.csv')

    # this spreadsheet is valid
    assert not a.valid
