#!/usr/bin/env python3

################################################################################
# stuff
################################################################################
import yaml
import sys
import datetime
from pathlib import Path

################################################################################
# stuff for user interaction
################################################################################
import questionary
from questionary.constants import DEFAULT_STYLE
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import FormattedText
from colorama import Fore, Style

def printSelected(message='', choice='', mark='?'):
	tokens = []
	tokens += [('class:qmark', mark)]
	tokens += [('class:question', f' {message} ')]
	tokens += [('class:answer', choice)]
	print_formatted_text(FormattedText(tokens), style=DEFAULT_STYLE)

################################################################################
# stuff api access
################################################################################
from warrant import Cognito #warrant
import requests

class DictObj:
	def __init__(self, in_dict):
		assert isinstance(in_dict, dict)
		for key, val in in_dict.items():
			if isinstance(val, (list, tuple)):
				setattr(self, key, [DictObj(x) if isinstance(x, dict) else x for x in val])
			else:
				setattr(self, key, DictObj(val) if isinstance(val, dict) else val)

class ICPC(requests.Session):
	def __init__(self, *args, **kwargs):
		super(ICPC, self).__init__(*args, **kwargs)

	def request(self, method, url, **kwargs):
		return super(ICPC, self).request(method, f'https://icpc.global/api/{url}', **kwargs)

	def get_list(self, url):
		list = self.get(url).json()
		return [DictObj(e) for e in list]

################################################################################
# read csv
################################################################################
import csv

class ExportDialect(csv.Dialect):
	delimiter = ','
	lineterminator = '\n'
	quotechar = '"'
	quoting = csv.QUOTE_MINIMAL
	strict = True

csv.register_dialect('export_dialect', ExportDialect)

################################################################################
# read .config
################################################################################
try:
	config_file = Path('.config.yaml')
	if config_file.exists():
		try:
			with open(config_file, 'r') as stream:
				login = yaml.safe_load(stream)
				username = login['username']
				password = login['password']
		except Exception as e:
			print(f'Could not read {config_file.name}!', file=sys.stderr)
			sys.exit(1)
		printSelected('Login Name?', username)
		printSelected('Login password?', '*' * len(password))
	else:
		username = questionary.text('Login Name?').unsafe_ask()
		password = questionary.password('Login password?').unsafe_ask()
		if questionary.confirm(f'Store in {config_file.name}?').unsafe_ask():
			login = {}
			login['username'] = username
			login['password'] = password
			with open(config_file, 'w') as stream:
				yaml.dump(login, stream)

################################################################################
# parse csv
################################################################################
	csv_file = Path('export.csv')
	participants = []
	with open(csv_file, 'r') as stream:
		reader = csv.DictReader(stream, dialect='export_dialect')
		fields = set(reader.fieldnames)
		assert 'Participant First Name' in fields
		assert 'Participant Name' in fields
		assert 'Participant E-Mail' in fields
		assert 'Team Name' in fields
		assert 'Contestsite' in fields
		assert 'Affiliation Name' in fields
		assert 'Contestsiteorganizer' in fields
		for row in reader:
			shortened = {}
			shortened['first'] = row['Participant First Name']
			shortened['last'] = row['Participant Name']
			shortened['mail'] = row['Participant E-Mail']
			shortened['team'] = row['Team Name']
			shortened['affiliation'] = row['Affiliation Name']
			shortened['contestsite'] = row['Contestsite']
			shortened['coach'] = row['Contestsiteorganizer']
			for k in shortened:
				assert shortened[k] is not None
			shortened['ascii'] = row['Team Name ASCII'] if 'Team Name ASCII' in row else None
			participants.append(DictObj(shortened))

	contestsites = {p.contestsite : DictObj({
		'name' : p.contestsite,
		'coach' : p.coach,
		'coach_id' : None,
		'id' : None,
	}) for p in participants}

	affiliations = {p.affiliation : DictObj({
		'name' : p.affiliation,
		'id' : None,
	}) for p in participants}

	teams = {}
	for p in participants:
		teams.setdefault(p.team, [])
		teams[p.team].append(p)
	teams = [DictObj({
		'name' : team,
		'ascii' : teams[team][0].ascii,
		'contestants' : teams[team],
		'contestsite' : teams[team][0].contestsite,
		'id' : None,
		'affiliation' : teams[team][0].affiliation,
	}) for team in teams]

################################################################################
# authenticate at icpc.global
################################################################################
	print()
	print('Accessing icpc.global...', end='', flush=True)

	#username
	#password
	client_id = '6q2fe6opm0m24eoebqf9vj4emd'
	pool_id = 'us-east-1_WaDOo4Gqm'

	aws_cognito = Cognito(pool_id, client_id, username=username, user_pool_region='us-east-1')
	aws_cognito.authenticate(password=password)
	headers = {'Authorization':  f'Bearer {aws_cognito.id_token}'}

	print('\rauthenticated!          ')
	print()

################################################################################
# add teams
################################################################################
	with ICPC() as icpc:
		icpc.headers = headers
		# guess current season
		year = datetime.datetime.now() + datetime.timedelta(days=365-31-28-31)
		year = questionary.text('Year?', str(year.year)).unsafe_ask()
		
		# select contest for this season
		contest = icpc.get_list(f'contest/tree/year/{year}')
		assert len(contest) > 0
		if len(contest) == 1:
			contest = contest[0]
			printSelected('Contest?', f'{contest.id}: {contest.label}')
		else:
			contest = questionary.select('Contest?', choices=[questionary.Choice(f'{c.id}: {c.label}', c) for c in contest]).unsafe_ask()

		# find all sites
		sites = icpc.get_list(f'contest/{contest.id}/sites')
		assert len(sites) > 0
		sites.sort(key=lambda e: e.name)
		print()
		printSelected('Found following sites with teams:', mark='!')
		for site in sites:
			if site.name in contestsites:
				contestsites[site.name].id = site.id
				coach = icpc.get_list(f'person/suggest?name={contestsites[site.name].coach}&page=1&size=2')
				if len(coach) == 1:
					coach = coach[0]
					contestsites[site.name].coach_id = coach.id
				coach_id = contestsites[site.name].coach_id
				if coach_id is None:
					coach_id = f'{Fore.RED}   ???{Style.RESET_ALL}'
				print('  {0:>6}: {1:<20} | {2:>7}: {3}'.format(site.id, site.name, coach_id, contestsites[site.name].coach))

		for name in contestsites:
			if contestsites[name].id is None:
				print(f'Missing contestsite for {name}')

		print()
		if not questionary.confirm('Continue with affiliations?', default=True, erase_when_done=True).unsafe_ask():
			sys.exit(1)

		# find all affiliations
		printSelected('Found following affiliations with teams:', mark='!')
		for name in affiliations:
			query_name = name.replace(' ', '+')
			affiliation = icpc.get_list(f'common/institutionunit/suggest?name={query_name}&page=1&size=2')
			if len(affiliation) == 1:
				affiliation = affiliation[0]
				affiliations[name].id = affiliation.id
			affiliation_id = affiliations[name].id
			if affiliation_id is None:
				affiliation_id = f'{Fore.RED}   ???{Style.RESET_ALL}'
			print('  {0:>6}: {1:<20}'.format(affiliation_id, name))

		print()
		if not questionary.confirm('Continue with import?', default=True, erase_when_done=True).unsafe_ask():
			sys.exit(1)

		#import teams
		for team in teams:
			contest_site_id = contestsites[team.contestsite].id
			coach_id = contestsites[team.contestsite].coach_id
			affiliation_id = affiliations[team.affiliation].id
			if contest_site_id is None or coach_id is None or affiliation_id is None:
				print(f'{team.name} incomplete informations: SKIPPING')
				continue

			# create team
			data = {
				'institutionUnitId' : affiliation_id,
				'name' : team.name,
				'siteId' : contest_site_id,
				'studentCoach' : False,
				'teamMembers' : [
					{
						'role' : 'COACH',
						'person': {'id' : coach_id},
					},
				],
			}
			res = icpc.post('team/register/customcoach', json=data)
			if res.status_code != 200:
				if team.ascii is not None and team.name != team.ascii:
					if questionary.confirm(f'{team.name} {Fore.RED}failed{Style.RESET_ALL}, retry as {team.ascii}?', default=True, erase_when_done=True).unsafe_ask():
						team.name = team.ascii
						data['name'] = team.ascii
						res = icpc.post('team/register/customcoach', json=data)
			if res.status_code != 200:
				print(f'{team.name} {Fore.RED}failed{Style.RESET_ALL} (SKIPPING)')
				# overrid team.id here for debug purposes if team was already created
				# skip the continue
				continue
			else:
				team.id = res.json()
			print(f'{team.name} created ({team.id})')

			# add contestants
			for contestant in team.contestants:
				contest_icpc = icpc.get_list(f'person/suggest?name={contestant.mail}&page=1&size=2')
				if len(contest_icpc) == 0:
					data = {
						'firstName' : contestant.first,
						'lastName' : contestant.last,
						'sex' : None,
						'title' : None,
						'username' : contestant.mail,
					}
					contest_icpc = icpc.post('person/registration/registerviasuggest', json=data)
					if contest_icpc.status_code != 200:
						print(f'  {contestant.first} {contestant.last} {Fore.RED}failed A{Style.RESET_ALL} (SKIPPING)')
						continue
					contest_icpc = DictObj(contest_icpc.json())
				elif len(contest_icpc) == 1:
					contest_icpc = contest_icpc[0]
				else:
					print(f'  {contestant.first} {contestant.last} {Fore.RED}failed B{Style.RESET_ALL} (SKIPPING)')
					continue

				data = [{
					'badgeRole': None,
					'certificateRole' : None,
					'person' : {
						'firstName' : contest_icpc.firstName,
						'id' : contest_icpc.id,
						'lastName' : contest_icpc.lastName,
						'username' : contest_icpc.username,
					},
					'role' : 'CONTESTANT',
				}]
				#we could add multiple users at once i guess?
				tmp = icpc.post(f'team/members/team/{team.id}/add', json=data)
				if tmp.status_code != 200:
					print(f'  {contestant.first} {contestant.last} {Fore.RED}failed C{Style.RESET_ALL} (SKIPPING)')
					continue

				print(f'  {contestant.first} {contestant.last} added')
except KeyboardInterrupt:
	print(f'\n{Fore.RED}Aborted!{Style.RESET_ALL}')
	sys.exit(1)
