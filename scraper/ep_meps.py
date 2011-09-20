#!../env/bin/python
# -*- coding: utf-8 -*-
#    This file is part of memopol2

#    memopol2 is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    memopol2 is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.

#    You should have received a copy of the GNU Affero General Public License
#    along with memopol2  If not, see <http://www.gnu.org/licenses/>.

# (C) 2011 by Stefan Marsiske, <stefan.marsiske@gmail.com>, Asciimoo

import sys

sys.path.append("/home/psycojoker/code/django/sqlmemopol2")
sys.path.append("/home/psycojoker/code/django/sqlmemopol2/apps")

import json, urllib2, sys, unicodedata
from datetime import datetime, date
from string import strip, uppercase
from lxml.html.soupparser import parse
from django.core.management import setup_environ
from memopol2 import settings
setup_environ(settings)
from reps.models import WebSite, Party, CV, Email, Opinion, OpinionREP, Representative, PartyRepresentative
from meps.models import Delegation, Committee, Country, Group, MEP, DelegationRole, CommitteeRole, Building
from django.core.exceptions import ObjectDoesNotExist

BASE_URL = 'http://www.europarl.europa.eu'
#proxy_handler = urllib2.ProxyHandler({'http': 'http://localhost:8123/'})
#opener = urllib2.build_opener(proxy_handler)
#("User-agent", "Mozilla/5.0 (Macintosh; U; PPC Mac OS X; en) AppleWebKit/125.2 (KHTML, like Gecko) Safari/125.8"),
opener = urllib2.build_opener()
opener.addheaders = [('User-agent', 'memopol2/0.8')]
urllib2.install_opener(opener)

def fetch(url, retries=3):
    for i in range(retries):
        try:
            return parse(urllib2.urlopen(url))
        except urllib2.HTTPError:
            pass
    return ''

def dateJSONhandler(obj):
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    else:
        raise TypeError, 'Object of type %s with value of %s is not JSON serializable' % (type(Obj), repr(Obj))

def getAddress(txts):
    flag = 0
    ret = {'Address': [], 'Phone': '', 'Fax': ''}
    for addr in txts:
        if not addr:
            continue
        if addr == 'Tel.':
            flag = 1
            continue
        elif addr == 'Fax':
            flag = 2
            continue
        if flag == 1:
            ret['Phone'] = addr[1:].strip()
        elif flag == 2:
            ret['Fax'] = addr[1:].strip()
        else:
            ret['Address'].append(addr)
    if len(ret['Address'])==7:
        ret['Address']=dict(zip(['Organization','Building','Office','Street','Zip1', 'Zip2', 'City'],ret['Address']))
    else:
        ret['Address']=dict(zip(['Organization','Building','Office','Street','Zip','City'],ret['Address']))
    return ret

def unws(txt):
    return ' '.join(strip(txt).split())

def splitDatedInfo(text,title):
    (period, text)=text.split(' : ',1)
    (start, end)=period.split(' / ',1)
    if end == '...':
        end='31.12.9999' # end of time
    item={title: text,
          'start': datetime.strptime(start,"%d.%m.%Y"),
          'end': datetime.strptime(end,"%d.%m.%Y")}
    return item

def parseMember(userid):
    url='http://www.europarl.europa.eu/members/expert/alphaOrder/view.do?language=EN&id=%s' % userid
    root = fetch(url)
    data = {'active': True}
    if not root or root.xpath('head/title/text()')=='The requested page does not exist.':
        return {'active': False}
    group=unws(''.join(root.xpath("//td[@style='width: 94%;']/span[@class='titlemep']/text()")))
    data['Groups'] = [{ 'role':  unws(''.join(root.xpath("//td[@style='width: 94%;']/span[@class='titlemep2']/text()"))),
                        'group': group,
                        'groupid': group_map[group]}]
    data['Photo'] = '' if not len(root.xpath("//img[@class='photoframe']")) else BASE_URL + root.xpath("//img[@class='photoframe']")[0].attrib['src']
    tmp = map(unws, root.xpath("//td[@class='mep_CVtext']/text()"))
    (d,p)=tmp[-1].split(',',1)
    data['Birth'] = { 'date': datetime.strptime(d, "Born on %d %B %Y"),
                      'place': p.strip() }
    data['Homepage'] = '' if not len(root.xpath("//td[@class='mepurl']/a/text()")) else root.xpath("//td[@class='mepurl']/a/text()")[0].strip()
    # LOL at HTML source - class="mepmail" -> obfuscation?! =))
    data['Mail'] = unws(''.join(root.xpath("//td[@class='mepmail']//text()")))
    data['Addresses'] = { 'Brussels': getAddress(map(strip, root.xpath("//td[@style='width: 225px; white-space: nowrap;']//text()"))),
                          'Strasbourg': getAddress(map(strip, root.xpath("//td[@style='width: 193px; white-space: nowrap;']//text()"))),
                          'Postal': [' '.join(x.split()) for x in root.xpath("//span[@class='txtmep']//text()") if x.strip()][1:]
                          }
    for c in root.xpath("//td[@class='mepcountry']"):
        key=unws(c.text)
        if (key in ['Member',
                    'Substitute',
                     'Chair',
                     'Vice-Chair',
                     'Co-President',
                     'President',
                     'Vice-President',
                     'Parliamentary activities'] or
            key.startswith('Parliamentary activities in plenary')):
            continue
        if key!='Curriculum vitae':
            print >>sys.stderr, '[!] unknown field', key
        else:
            key='CV'
        data[key] = []
        for cc in c.xpath("../../tr[@class='mep_CVtext']/td[2]"):
            data[key].append(cc.text if not len(cc.xpath('a')) else (cc.text.strip(), BASE_URL+cc.xpath('a')[0].attrib['href']))

    # process info of Constituencies
    group=root.xpath("//span[@class='titlemep']/text()")[0].strip()
    country=''.join([' '.join(x.split()).strip() for x in root.xpath("//table[@class='titlemep']//td//text()") if ' '.join(x.split()).strip()])
    
    # There is multiple parties named "Partido Popular" cf. https://projets.lqdn.fr/issues/273
    if group == "Partido Popular":
        if country == 'Portugal':
            group += ' (PT)'
        elif country == 'Spain':
            group += ' (ES)'
    
    data['Constituencies']={'country': country, 'party': group}
    # process other historical data
    for c in root.xpath("//td[@class='mepcountry']"):
        data=parseRoles(c, data)
    return data

def mangleName(name):
    family=name.split(', ')[0]
    try:
        sur=name.split(', ')[1]
    except:
        sur=''
    title=None
    for t in Titles:
        if family.startswith(t):
            family=family[len(t)+1:]
            title=t
            break
    res= { 'full': name,
           'sur': sur,
           'family': family,
           'familylc': family.lower(),
           'aliases': [family,
                       family.lower(),
                       ''.join(family.split()).lower(),
                       "%s %s" % (sur, family),
                       "%s %s" % (family, sur),
                       ("%s %s" % (family, sur)).lower(),
                       ("%s %s" % (sur, family)).lower(),
                       ''.join(("%s%s" % (sur, family)).split()),
                       ''.join(("%s%s" % (family, sur)).split()),
                       ''.join(("%s%s" % (family, sur)).split()).lower(),
                       ''.join(("%s%s" % (sur, family)).split()).lower(),
                      ],}
    if title:
        res['title']=title
        res['aliases'].extend([("%s %s" % (title, family)).strip(),
                               ("%s %s %s" % (title ,family, sur)).strip(),
                               ("%s %s %s" % (title, sur, family)).strip(),
                               ("%s %s %s" % (title, family, sur)).strip(),
                               ("%s %s %s" % (title, sur, family)).lower().strip(),
                               ("%s %s %s" % (title, family, sur)).lower().strip(),
                               (''.join(("%s%s%s" % (title, family, sur)).split())).strip(),
                               (''.join(("%s%s%s" % (title, sur, family)).split())).strip(),
                               (''.join(("%s%s%s" % (sur, title, family)).split())).strip(),
                               (''.join(("%s%s%s" % (sur, family, title)).split())).strip(),
                               ''.join(("%s%s%s" % (family, sur, title)).split()).lower().strip(),
                               ''.join(("%s%s%s" % (family, title, sur)).split()).lower().strip(),
                               ''.join(("%s%s%s" % (title, family, sur)).split()).lower().strip(),
                               ''.join(("%s%s%s" % (title, sur, family)).split()).lower().strip(),
                               ])
    if  u'ß' in unicode(name):
        res['aliases'].extend([x.replace(u'ß','ss') for x in res['aliases']])
    if unicodedata.normalize('NFKD', unicode(name)).encode('ascii','ignore')!=name:
        res['aliases'].extend([unicodedata.normalize('NFKD', x).encode('ascii','ignore') for x in res['aliases']])
    if "'" in name:
        res['aliases'].extend([x.replace("'","") for x in res['aliases']])
    if name in meps_aliases:
           res['aliases'].extend(meps_aliases[name])
    return res

def parseRoles(c, data):
    key=unws(c.text)
    if key.startswith('Parliamentary activities'):
        return data # all urls can be recreated from the UserID
    for cc in c.xpath("../../tr[@class='mep_CVtext']/td[2]"):
        name=' '.join(cc.xpath('string()').split())
        item={ 'Organization': name }
        item['role']=key
        if len(cc.xpath('a')):
            item['url']=BASE_URL+cc.xpath('a')[0].attrib['href']
        found=False
        for start, field in orgmaps:
            if item['Organization'].startswith(start):
                if not field in data:
                    data[field]=[]
                data[field].append(item)
                found=True
                break
        if found:
            continue
        if item['Organization'] in GROUPS or item['Organization'] in group_map:
                if not 'Groups' in data:
                    data['Groups']=[]
                if item['Organization'] in group_map:
                    item['groupid']=group_map[item['Organization']]
                # TODO find out exact date of when the 2001 term started
                #elif item['start']>datetime.strptime("30092001","%d%m%Y"):
                #    print >>sys.stderr, '[!] unrecognized group', key, item
                data['Groups'].append(item)
                continue
        print >>sys.stderr, '[!] unrecognized data', key, item
    return data

def scrape(userid, name):
    data = { 'Constituencies': [],
             'Name' : mangleName(name),
             'Groups': [],
             'UserID': userid }
    # retrieve supplemental info for currently active meps
    data.update(parseMember(userid))
    #save(data)
    print json.dumps(data, indent=1, default=dateJSONhandler, ensure_ascii=False).encode('utf-8')

class CachedQuery():
    cache={}
    coll=None

    def __init__(self, coll):
        self.cache={}
        self.coll=coll

    def fetch(self,id,query,data):
        print id, query, data
        if id in self.cache:
            return self.cache[id]
        try:
            res=self.coll.objects.get(**query)
        except ObjectDoesNotExist:
            res=self.coll.objects.create(**data)
        self.cache[id]=res
        return res
Parties=CachedQuery(Party)
# name=group["party"]
Groups=CachedQuery(Group)
# abbreviation=g["abbreviation"]
Countries=CachedQuery(Country)
#code=c["code"]
Delegations=CachedQuery(Delegation)
#name=d["label"]
Committees=CachedQuery(Committee)
# name=c["label"], abbreviation=c["abbreviation"]
Bxls=CachedQuery(Building)
Stbs=CachedQuery(Building)

bmaps={'Willy Brandt': 'WIB',
       'Louise Weiss': 'LOW',
       'Altiero Spinelli': 'ASP',
       'Winston Churchill': 'WIC',
       'Paul-Henri Spaak': 'PHS',
       'Atrium': 'ATR',
       'Moving': '-'
       }
def getBuilding(b,q):
    name=' '.join(b['Building'].split()[1:])
    obj= { 'name': name,
           'id': bmaps[name],
           'street': b["Street"]}
    if 'Zip' in b:
           obj['postcode']=b["Zip"]
    else:
           obj['postcode']=b["Zip1"]
    return q.fetch(name,
            {'name':name}, obj)

wiki_maps={}
def _create_mep(mep):
    if MEP.objects.get(ep_id=mep['UserID']):
        print mep['Name']['full'],'exists'
        return
    wiki=wiki_maps.get(mep['UserID'],
                       "%s%s"% (mep['Name']['sur'].title(),mep['Name']['family'].title()))
    c=SEIRTNUOC[mep["Constituencies"]["country"]]
    country=Countries.fetch(c,{'code':c},{'code':c})
    m={ 'active': True,
        'id': wiki,
        'first_name': mep['Name']["sur"],
        'last_name': mep['Name']["family"],
        'full_name': mep['Name']["full"],
        # TODO gender=mep["infos"]["gender"],
        'picture': "%s.jpg" % wiki,
        'ep_id': mep["UserID"],
        # Uneccessary ep_opinions=mep["activities"]["opinions"],
        # Uneccessary ep_debates=mep["activities"]["debates"],
        # Uneccessary ep_questions=mep["activities"]["questions"],
        # Uneccessary ep_declarations=mep["activities"]["declarations"],
        # Uneccessary ep_reports=mep["activities"]["reports"],
        # Uneccessary ep_motions=mep["activities"]["motions"],
        'group_role': mep["Groups"][0]["role"],
        'group': Group.objects.get(abbreviation=mep["Groups"][0]["groupid"]),
        'country': country}

    m['birth_place']= "unknown"
    m['birth_date']= date(9999,12,31)
    if 'Birth' in mep:
        m['birth_place']= mep["Birth"]["place"]
        d=mep["Birth"]['date']
        m['birth_date']= date(d.year,d.month,d.day)

    if 'Homepage' in mep:
        m['ep_webpage']=mep["Homepage"]
    if 'Addresses' in mep:
        m.update({'bxl_building': getBuilding(mep['Addresses']['Brussels']['Address'],Bxls),
                  'bxl_office': mep["Addresses"]["Brussels"]['Address']["Office"],
                  'bxl_fax': mep["Addresses"]["Brussels"]["Fax"],
                  'bxl_phone1': mep["Addresses"]["Brussels"]["Phone"],
                  # TODO not scraped, needs to be calculated?
                  # bxl_phone2': mep["Addresses"]["Brussels"]["phone"][1],
                  'stg_building': getBuilding(mep['Addresses']['Strasbourg']['Address'],Stbs),
                  'stg_office': mep["Addresses"]["Strasbourg"]["Address"]["Office"],
                  'stg_fax': mep["Addresses"]["Strasbourg"]["Fax"],
                  'stg_phone1': mep["Addresses"]["Strasbourg"]["Phone"],
                  # TODO not scraped, needs to be calculated?
                  # stg_phone2=mep["Addresses"]["Strasbourg"]["phone"][1],
                  })

    _mep = MEP.objects.create(**m)

    Email.objects.create(email=mep["Mail"], representative=_mep)

    if mep["Homepage"]:
            WebSite.objects.create(url=mep["Homepage"], representative=_mep)

    party=Parties.fetch(mep["Constituencies"][0]["party"],{'name': mep["Constituencies"][0]["party"]},{'name': mep["Constituencies"][0]["party"]})
    PartyRepresentative.objects.create(party=party, representative=_mep, current=True)

    return _mep



def save(data):
    _mep = _create_mep(data)
    for d in data['Delegations']:
        delegation=Delegations.fetch(d['Organization'],{'name': d['Organization']},{'name': d['Organization']})
        DelegationRole.objects.create(mep=_mep, role=d["role"], delegation=delegation)
    for d in data['Committees']:
        committee=Committees.fetch(d['Organization'],{'name': d['Organization']},{'name': d['Organization']})
        CommitteeRole.objects.create(mep=_mep, role=bd["role"], committee=committee)
    if data["cv"]:
        if type(cv) is list:
            for c in cv:
                CV.objects.create(title=c, representative=_mep)
            else:
                CV.objects.create(title=cv, representative=_mep)

group_map={ "Confederal Group of the European United Left - Nordic Green Left": 'GUE/NGL',
            "Confederal Group of the European United Left-Nordic Green Left": 'GUE/NGL',
            'Confederal Group of the European United Left / Nordic Green Left': 'GUE/NGL',
            'Confederal Group of the European United Left/Nordic Green Left': 'GUE/NGL',
            "European Conservatives and Reformists": 'ECR',
            'European Conservatives and Reformists Group': 'ECR',
            "Europe of freedom and democracy Group": 'EFD',
            'Europe of Freedom and Democracy Group': 'EFD',
            "Group of the Alliance of Liberals and Democrats for Europe": 'ALDE',
            "Group of the Greens/European Free Alliance": "Verts/ALE",
            "Group of the Progressive Alliance of Socialists and Democrats in the European Parliament": "S&D",
            "Non-attached Members": "NI",
            'Group for a Europe of Democracies and Diversities': 'EDD',
            'Group of the European Liberal Democrat and Reform Party': 'ELDR',
            'Group of the European Liberal, Democrat and Reform Party': 'ELDR',
            'Group indépendence/Démocratie': ['ID','INDDEM', 'IND/DEM'],
            'Independence/Democracy Group': ['ID', 'INDDEM', 'IND/DEM'],
            'Identity, Tradition and Sovereignty Group': 'ITS',
            'Non-attached Members': ['NA','NI', 'IND/DEM'],
            'Non-attached': ['NA','NI', 'IND/DEM'],
            "Group of the European People's Party (Christian Democrats) and European Democrats": 'PPE-DE',
            "Group of the European People's Party (Christian Democrats)": 'PPE',
            "Group of the European People's Party (Christian-Democratic Group)": "PPE",
            'Group of the Party of European Socialists': 'PSE',
            'Socialist Group in the European Parliament': 'PSE',
            'Technical Group of Independent Members': 'TDI',
            'Group indépendence/Démocratie': 'UEN',
            'Union for a Europe of Nations Group': 'UEN',
            'Union for Europe of the Nations Group': 'UEN',
            'Group of the Greens / European Free Alliance': 'Verts/ALE',
            'Greens/EFA': 'Verts/ALE',
            }

orgmaps=[('Committee o', 'Committees'),
        ('Temporary committee ', 'Committees'),
        ('Temporary Committee ', 'Committees'),
        ('Subcommittee on ', 'Committees'),
        ('Special Committee ', 'Committees'),
        ('Special committee ', 'Committees'),
        ('Legal Affairs Committee', 'Committees'),
        ('Political Affairs Committee', 'Committees'),
        ('Delegation','Delegations'),
        ('Members from the European Parliament to the Joint ', 'Delegations'),
        ('Membres fron the European Parliament to the ', 'Delegations'),
        ('Conference of ', 'Staff'),
        ("Parliament's Bureau", 'Staff'),
        ('European Parliament', 'Staff'),
        ('Quaestors', 'Staff'),]

GROUPS=[
   'Communist and Allies Group',
   'European Conservative Group',
   'European Conservatives and Reformists',
   'European Democratic Group',
   'Europe of freedom and democracy Group',
   'Europe of Nations Group (Coordination Group)',
   'Forza Europa Group',
   'Confederal Group of the European United Left',
   'Confederal Group of the European United Left/Nordic Green Left',
   'Confederal Group of the European United Left - Nordic Green Left',
   'Christian-Democratic Group',
   "Christian-Democratic Group (Group of the European People's Party)",
   "Group of the European People's Party ",
   'Group for a Europe of Democracies and Diversities',
   'Group for the European United Left',
   'Group for the Technical Coordination and Defence of Indipendent Groups and Members',
   'Group of Independents for a Europe of Nations',
   'Group of the Alliance of Liberals and Democrats for Europe',
   'Group of the European Democratic Alliance',
   'Group of the European Liberal, Democrat and Reform Party',
   'Group of the European Radical Alliance',
   'Group of the European Right',
   'Group of the Greens/European Free Alliance',
   'Group of the Party of European Socialists',
   'Group of the Progressive Alliance of Socialists and Democrats in the European Parliament',
   'European Democratic Union Group',
   'Group of European Progressive Democrats',
   "Group of the European People's Party (Christian Democrats) and European Democrats",
   "Group of the European People's Party (Christian Democrats)",
   'Group Union for Europe',
   'Identity, Tradition and Sovereignty Group',
   'Independence/Democracy Group',
   'Left Unity',
   'Liberal and Democratic Group',
   'Liberal and Democratic Reformist Group',
   'Non-attached',
   'Non-attached Members',
   "Rainbow Group: Federation of the Green Alternative European Links, Agelev-Ecolo, the Danish People's Movement against Membership of the European Community and the European Free Alliance in the European Parliament",
   'Rainbow Group in the European Parliament',
   'Socialist Group',
   'Socialist Group in the European Parliament',
   'Technical Coordination and Defence of Independent Groups and Members',
   'Technical Group of Independent Members - mixed group',
   'Technical Group of the European Right',
   'The Green Group in the European Parliament',
   'Union for Europe of the Nations Group', ]

groupids=[]
for item in group_map.values():
    if type(item)==list:
        groupids.extend(item)
    else:
        groupids.append(item)

meps_aliases={
    u"GRÈZE, Catherine": ['GREZE', 'greze', 'Catherine Greze', 'catherine greze', u'Grčze', u'grcze'],
    u"SCOTTÀ, Giancarlo": ["SCOTTA'", "scotta'"],
    u"in 't VELD, Sophia": ["in't VELD", "in't veld", "IN'T VELD", "in'tveld"],
    u"MORKŪNAITĖ-MIKULĖNIENĖ, Radvilė": [u"MORKŪNAITĖ Radvilė",u"morkūnaitė radvilė",u"radvilė morkūnaitė ",u"Radvilė MORKŪNAITĖ ", u"MORKŪNAITĖ", u"morkūnaitė"],
    u"MUSTIN-MAYER, Christine": ['Barthet-Mayer Christine', 'barthet-mayer christine', 'barthet-mayerchristine'],
    u"YÁÑEZ-BARNUEVO GARCÍA, Luis": [ u'Yañez-Barnuevo García', u'yañez-barnuevogarcía', u'Luis Yañez-Barnuevo García', u'luisyanez-barnuevogarcia'],
    u"ZAPPALA', Stefano": [ u'Zappalà', u'zappalà'],
    u"OBIOLS, Raimon": [u'Obiols i Germà', u'obiols i germà', u'ObiolsiGermà', u'obiolsigermà', u'Raimon Obiols i Germà', u'raimonobiolsigermà' ],
    u"CHATZIMARKAKIS, Jorgo": [u'Chatzimartakis', u'chatzimartakis'],
    u"XENOGIANNAKOPOULOU, Marilisa": [u'Xenagiannakopoulou', u'xenagiannakopoulou'],
    u"GRÄSSLE, Ingeborg": [u'Graessle', u'graessle'],
    u"VIRRANKOSKI, Kyösti": [u'Virrankoski-Itälä', u'virrankoski-itälä'],
    u"SARYUSZ-WOLSKI, Jacek": [u'Saryus-Wolski', u'saryus-wolski'],
    u"PITTELLA, Gianni": [u'Pitella', u'pitella'],
    u"EHLER, Christian": [u'Ehlert', u'ehlert', u'Jan Christian Ehler', u'janchristianehler'],
    u"COELHO, Carlos": [u'Coehlo', u'coehlo'],
    u"Ó NEACHTAIN, Seán": [u"O'Neachtain", u"o'neachtain"],
    u"GALEOTE, Gerardo": [u'Galeote Quecedo', u'galeote quecedo',u'GaleoteQuecedo', u'galeotequecedo'],
    u'MARTIN, Hans-Peter': [u'Martin H.P.',u'martinh.p.', u'mmHans-Peter Martin', u'mmhans-petermartin' ],
    u'MARTIN, David': [u'D. Martin', u'd. martin', u'D.Martin', u'd.martin', u'Martin David W.', u'martindavidw.'],
    u'DÍAZ DE MERA GARCÍA CONSUEGRA, Agustín': [u'Díaz de Mera', u'díazdemera'],
    u'MEYER, Willy': [u'Meyer Pleite', u'meyer pleite', u'MeyerPleite', u'meyerpleite', u'Willy Meyer Pleite', u'willymeyerpleite'],
    u'ROBSAHM, Maria': [u'Carlshamre', u'carlshamre'],
    u'HAMMERSTEIN, David': [u'Hammerstein Mintz', u'hammersteinmintz'],
    u'AYUSO, Pilar': [u'Ayuso González', u'ayusogonzález'],
    u'PÖTTERING, Hans-Gert': [u'Poettering', u'poettering'],
    u'VIDAL-QUADRAS, Alejo': [u'Vidal-Quadras Roca', u'vidal-quadrasroca'],
    u'EVANS, Jill': [u'Evans Jillian', u'evansjillian'],
    u'BADIA i CUTCHET, Maria': [u'Badía i Cutchet', u'badíaicutchet', u'Badia Cutchet', u'badiacutchet'],
    u'AUCONIE, Sophie': [u'Briard Auconie', u'briardauconie', u'Sophie Briard Auconie', u'sophiebriardauconie'],
    u'BARSI-PATAKY, Etelka': [u'Barsi Pataky', u'barsipataky'],
    u'NEYNSKY, Nadezhda': [u'Mihaylova', u'mihaylova', u'Nadezhda Mihaylova', u'nadezhdamihaylova'],
    u'MOHÁCSI, Viktória': [u'Bernáthné Mohácsi', u'bernáthnémohácsi', u'bernathnemohacsi'],
    u'WOJCIECHOWSKI, Bernard': [u'Wojciechowski Bernard Piotr', u'wojciechowskibernardpiotr'],
    u'GARCÍA-MARGALLO Y MARFIL, José Manuel': [u'García-MarGállo y Marfil', u'garcía-margálloymarfil'],
    u'ROGALSKI, Bogusław': [u'RoGálski', u'rogalski'],
    u'ROMEVA i RUEDA, Raül': [u'Romeva Rueda', u'romevarueda', u'Raьl Romeva i Rueda', u'raьlromevairueda'],
    u'JØRGENSEN, Dan': [u'Dan Jшrgensen', u'danjшrgensen', u'dan jшrgensen'],
    u'HÄFNER, Gerald': [u'Haefner', u'haefner', u'Gerald Haefner', u'geraldhaefner'],
    u'EVANS, Robert': [u'Evans Robert J.E.', u'evansrobertj.e.'],
    u'LAMBSDORFF, Alexander Graf': [u'Lambsdorff Graf', u'lambsdorffgraf'],
    u'STARKEVIČIŪTĖ, Margarita': [u'Starkeviciūtė', u'starkeviciūtė'],
    u'KUŠĶIS, Aldis': [u'Kuškis', u'kuškis'],
    u'ŠŤASTNÝ, Peter': [u'Štastný', u'štastný'],
    u'FLAŠÍKOVÁ BEŇOVÁ, Monika': [u'Beňová', u'beňová'],
    u'ŢÎRLE, Radu': [u'Tîrle', u'tîrle'],
    u'HYUSMENOVA, Filiz Hakaeva': [u'Husmenova', u'husmenova'],
    }

Titles=['Sir',
       'Lady',
       'Baroness',
       'Baron',
       'Lord',
       'Earl',
       'Duke',
       'The Earl of',
       'The Lord',
       'Professor Sir']

COUNTRIES = {'BE': 'Belgium',
             'BG': 'Bulgaria',
             'CZ': 'Czech Republic',
             'DK': 'Denmark',
             'DE': 'Germany',
             'EE': 'Estonia',
             'IE': 'Ireland',
             'EL': 'Greece',
             'ES': 'Spain',
             'FR': 'France',
             'IT': 'Italy',
             'CY': 'Cyprus',
             'LV': 'Latvia',
             'LT': 'Lithuania',
             'LU': 'Luxembourg',
             'HU': 'Hungary',
             'MT': 'Malta',
             'NL': 'Netherlands',
             'AT': 'Austria',
             'PL': 'Poland',
             'PT': 'Portugal',
             'RO': 'Romania',
             'SI': 'Slovenia',
             'SK': 'Slovakia',
             'FI': 'Finland',
             'SE': 'Sweden',
             'GB': 'United Kingdom',
             }

SEIRTNUOC = {'Belgium': 'BE',
             'Bulgaria': 'BG',
             'Czech Republic':'CZ',
             'Denmark': 'DK',
             'Germany': 'DE',
             'Estonia': 'EE',
             'Ireland': 'IE',
             'Greece': 'EL',
             'Spain': 'ES',
             'France': 'FR',
             'Italy': 'IT',
             'Cyprus': 'CY',
             'Latvia': 'LV',
             'Lithuania': 'LT',
             'Luxembourg': 'LU',
             'Hungary': 'HU',
             'Malta': 'MT',
             'Netherlands': 'NL',
             'Austria': 'AT',
             'Poland': 'PL',
             'Portugal': 'PT',
             'Romania': 'RO',
             'Slovenia': 'SI',
             'Slovakia': 'SK',
             'Finland': 'FI',
             'Sweden': 'SE',
             'United Kingdom':'GB',
             }

if __name__ == "__main__":
    for letter in uppercase:
        root = fetch("http://www.europarl.europa.eu/members/expert/alphaOrder.do?letter=%s&language=EN" % letter)
        for data in  root.xpath("//td[@class='box_content_mep']/table/tr/td[2]"):
            userid=dict([x.split('=') for x in data.xpath("a")[0].attrib['href'].split('?')[1].split('&')])['id']
            print >>sys.stderr,data.xpath('a/text()')[0].encode('utf8')
            scrape(userid,data.xpath('a/text()')[0])
