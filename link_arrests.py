"""
script to link arrest reports stored in documentcloud to arrestees

to use:

python -i scripts/helpers/documentcould_arrests.py
(runs for yesterday's arrests)

OR

python -i scripts/helpers/documentcould_arrests.py [DATE in form dd-mm-YYYY]
(date of your choosing)

OR

python manage.py.shell
from scripts.helpers.documentcloud_arrests import *
targ_date = datetime.date(2014, 9, 28)
link_reports(targ_date)

"""

import os
import sys
import json
import datetime
from datetime import timedelta
from dateutil import parser
from collections import OrderedDict

import requests

from django.core.mail import send_mail
from django.core.management import setup_environ
sys.path.append('/opt/django-projects/.virtualenvs/crime/arrests/watcher/')
import settings
setup_environ(settings)
from django.db.models import Q
from arrestee.models import Arrestee
from places.models import County
PIN = County.objects.get(name='Pinellas')

today = datetime.datetime.now().date()
targ_date = today - timedelta(days=2)
# targ_date = today - timedelta(days=1)
# targ_date = datetime.date(2014, 9, 24)
try:
    dc_id = os.getenv('DCLOUD_ID')
    dc_pass = os.getenv('DCLOUD_PASS')
except:
    print "environment secrets failed"
    sys.exit()
dc_root = 'https://www.documentcloud.org'
doc_base = "%s/documents" % dc_root
api_base = '%s/api' % dc_root
token1 = 'above named defendant'
token2 = 'Victim Notified'
searchbase = "%s/search.json" % api_base

authroot = 'https://%s:%s@www.documentcloud.org' % (dc_id.replace('@', '%40'), dc_pass)
project_id = '15804'# the documentcloud ID for the tampabay times' 'pinellas_arrest_reports' project

def search_tbdocs(bid, tbdocs):
    for doc in sorted(tbdocs.keys(), reverse=True):
        doctest = requests.get(tbdocs[doc]['search'].replace('{query}', bid)).json()
        if 'results' in doctest and doctest['results']:
            return doc, sorted(doctest['results'])
        else:
            return '', []

def link_reports(date):
    count = 0
    proj = requests.get("%s/api/search.json?q=projectid:%s&per_page=1000" % (authroot, project_id)).json()
    tbdocs = {}
    for doc in proj['documents']:
        tbdocs[doc['id']]=doc['resources']
    arrests = Arrestee.objects.filter( Q(arrest_notes__isnull=True) | Q(arrest_notes='') ).filter(booking_county=PIN, arrest_date__gte=date)
    for ar in arrests:
        slug, pages = search_tbdocs(ar.booking_id, tbdocs)
        if slug:
            DOC = tbdocs[slug]
            report = OrderedDict()
            for page in pages:
                report[page] = {'text_url': DOC['page']['text'].replace('{page}', '%s' % page), 'pdf': DOC['page']['image'].replace('{page}', '%s' % page).replace('{size}', 'large')}
            for page in report:
                raw = requests.get(report[page]['text_url']).text
                if token1 in raw and token2 in raw:
                    report[page]['text'] = raw.split(token1)[1].split(token2)[0]
                else:
                    print "couldn't parse arrest report page %s for %s (booking id %s)" % (page, ar, ar.booking_id)
                    report[page]['text'] = ''
            ar.arrest_notes ="\n<br>".join([report[page]['text'] for page in report])[:3500]
            ar.arrest_pdf = "%s/%s.html" % (doc_base, slug)
            ar.report1 = report[report.keys()[0]]['pdf']
            if len(report) > 1:
                ar.report2 = report[report.keys()[1]]['pdf']
            if len(report) >2:
                ar.arrest_notes = '%s\n<br>THIS ARREST covers more than two pages; see the <a href="%s">FULL PDF</a>, starting at page %s' % (ar.arrest_notes, ar.arrest_pdf, report.keys()[0])
            else:
                ar.arrest_notes = '%s\n<br><a href="%s">FULL PDF</a> (go to page %s)' % (ar.arrest_notes, ar.arrest_pdf, report.keys()[0])
            ar.save()
            print "linked arrest info for %s" % ar
            count += 1
        else:
            print "couldn't find arrest report for %s (booking Id %s, arrest date %s)" % (ar, ar.booking_id, ar.arrest_date)
    endmsg = "linked %s arrest records (%s percent of %s arrests on or after %s)" % (count, (count*100.0/arrests.count()), arrests.count(), date)
    print endmsg
    if count > 0:
        send_mail('arrest linker update', endmsg, 'tbtimes.watcher@gmail.com', ['higs4281@gmail.com'], fail_silently=False)

if __name__ == "__main__":
    if len(sys.argv) >1:
        try:
            param = sys.argv[1]
        except:
            print "shell usage: python documentcloud_arrests.py [dd-mm-YYYY]"
            sys.exit()
        else:
            targ_date = parser.parse(param).date()
            link_reports(targ_date)
    else:
        link_reports(targ_date)
