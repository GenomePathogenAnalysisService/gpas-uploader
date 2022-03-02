# from openpyxl import load_workbook
import json, csv, copy
import sys
from pathlib import Path
import datetime
import shutil
import hashlib
import uuid
import subprocess
import b24
from collections import defaultdict

from error import GpasError

def hash(fn):
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    with open(fn, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()

if Path("./samtools").exists():
    samtools = Path("./samtools").resolve()

# or if there is one in the $PATH use that one
elif shutil.which('samtools') is not None:
    samtools = Path(shutil.which('samtools'))

else:
    raise GpasError({"BAM conversion": "samtools not found"})

# shared_columns={'name','organisation','tags','specimenOrganism','host','collectionDate','country','submissionTitle','submissionDescription','instrument_platform','instrument_model','flowcell'}
#
# illumina_columns=copy.deepcopy(shared_columns)
# illumina_columns.add('fastq1')
# illumina_columns.add('fastq2')
#
# nanopore_columns=copy.deepcopy(shared_columns)
# nanopore_columns.add('fastq')


def parse_row(d, using_bams, wd=None):

    errors = []
    samples = []

    # insist that the collectionDate is in the ISO format.
    # the Electron client will then enforce YYYY-MM for organisations that consider this PII
    # hence the precise date will not leave their network
    try:
        datetime.date.fromisoformat(d["collectionDate"])
    except ValueError:
        errors.append({"sample": d["name"], "error": "collectionDate not in ISO format"})

    # check that all samples have at least one tag
    if d['tags'] == '':
        errors.append({"sample": d["name"], "error": "must have at least one tag"})

    # treat the samples differently depending on sequencing instrument
    if "Illumina" in d["instrument_platform"]:

        # if it contains BAM files, we first need to run samtools to create FASTQ files
        if using_bams:

            stem = d['bam'].split('.bam')[0]

            process1 = subprocess.Popen(
                [
                    samtools,
                    'sort',
                    '-n',
                    wd / Path(d['bam'])
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            process2 = subprocess.run(
                [
                    samtools,
                    'fastq',
                    '-N',
                    '-1',
                    wd / Path(stem + "_1.fastq.gz"),
                    '-2',
                    wd / Path(stem+"_2.fastq.gz"),
                ],
                stdin = process1.stdout,
                stdout = subprocess.PIPE,
                stderr = subprocess.PIPE
            )

            # to stop a race condition
            process1.wait()

            # insist that the above command did not fail
            assert process2.returncode == 0, 'samtools command failed'

            # now record the names of the FASTQ files in the dict
            d['fastq1'] = stem + "_1.fastq.gz"
            d['fastq2'] = stem + "_2.fastq.gz"

        fq1_path = wd / Path(d["fastq1"])
        fq2_path = wd / Path(d["fastq2"])

        # check that the FASTQ files specified in the upload CSV exist
        if not fq1_path.exists() or not fq2_path.exists():
            errors.append({"sample": d["name"], "error": "file-missing"})

        return Sample(fq1=fq1_path, fq2=fq2_path, data=d), errors

    elif "Nanopore" in d["instrument_platform"]:

        # if it contains BAM files, we first need to run samtools to create FASTQ files
        if using_bams:

            stem = d['bam'].split('.bam')[0]

            process = subprocess.Popen(
                [
                    samtools,
                    'fastq',
                    '-o',
                    wd / Path(stem + '.fastq.gz'),
                    wd / Path(d['bam'])
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # wait for it to finish otherwise the file will not be present
            process.wait()

            # successful completion
            assert process.returncode == 0, 'samtools command failed'

            # now that we have a FASTQ, add it to the dict
            d["fastq"] = stem + '.fastq.gz'

        fq_path = wd / Path(d["fastq"])

        if not fq_path.exists():
            errors.append({"sample": d["name"], "error": "file-missing"})

        return Sample(fq1=fq_path, data=d), errors

    else:
        errors.append({"sample": d["name"], "error": "bad-instrument"})
        return Sample(fq1=None, data=d), errors

class Sample:

    name = None
    data = {}
    fq1 = None
    fq2 = None

    def __init__(self, fq1, fq2=None, data=None):
        if data:
            self.data = data

        # by default choose an RFC 4122
        self.name = str(uuid.uuid4())
        self.fq1 = fq1
        self.fq2 = fq2

    def files(self):
        if not self.fq2:
            return [str(self.fq1.name)]
        else:
            return [str(self.fq1.name), str(self.fq2.name)]

    def add_pe(self, fq1, fq1md5, fq2, fq2md5, batchname):
        self.data["peReads"] = [
            {"r1_uri": str(batchname / fq1), "r1_md5": fq1md5},
            {"r2_uri": str(batchname / fq2), "r2_md5": fq2md5},
        ]

    def add_se(self, fq, fqmd5, batchname):
        self.data["seReads"] = [{"uri": str(batchname / fq), "md5": fqmd5}]
        # self.name = f"S2{fqmd5[:8]}"

    def to_submission(self):
        j = {
            "name": self.name,
            "tags": self.data['tags'].split(':'),
            "specimenOrganism": self.data["specimenOrganism"],
            "host": self.data["host"],
            "collectionDate": self.data["collectionDate"],
            "country": self.data["country"],
            "submissionTitle": self.data["submissionTitle"],
            "submissionDescription": self.data["submissionDescription"],
            "status": "Uploaded",
            "instrument": {
                "platform": self.data["instrument_platform"],
                "model": self.data["instrument_model"],
                "flowcell": self.data["flowcell"],
            },
        }

        if "peReads" in self.data:
            j["peReads"] = self.data["peReads"]
        elif "seReads" in self.data:
            j["seReads"] = self.data["seReads"]
        return j


class Samplesheet:
    samples = []
    batch = None
    parent = None
    site = None
    org = None
    errors = []

    def __init__(self, fn, fastq_prefix=None):

        self.parent = fn.parent

        # check to see if this upload CSV file specifies BAM files (rather than FASTQs)
        with open(fn, "r") as fd:
            using_bams = True if 'bam' in fd.readline() else False

        with open(fn, "r") as fd:
            reader = csv.DictReader(fd)

            for index, row in enumerate(reader):
                rowdata, rowerror = parse_row(row, using_bams, wd=self.parent)

                if not rowerror:
                    self.samples.append(rowdata)
                else:
                    for err in rowerror:
                        self.errors.append(err)

                self.org = rowdata.data["organisation"]
            _, shasum = hash(fn)
            self.batch = f"B-{b24.name(fn)}"

    def validate(self):
        if not self.errors:
            samples = []
            for sample in self.samples:
                samples.append({"sample": sample.name, "files": sample.files()})

            return {"validation": {"status": "completed", "samples": samples}}
        else:
            return {"validation": {"status": "failure", "samples": self.errors}}

    def make_submission(self):
        currentTime = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec='milliseconds')
        tzStartIndex = len(currentTime) - 6
        currentTime = currentTime[:tzStartIndex] + "Z" + currentTime[tzStartIndex:]
        return {
            "submission": {
                "batch": {
                    "fileName": self.batch,
                    "organisation": self.org,
                    "uploadedOn": currentTime,
                    "samples": [s.to_submission() for s in self.samples],
                }
            }
        }
