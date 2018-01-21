import re, math, os, sys
import datetime, time
import urllib.request, html
import sqlite3

################################################################################
# pulls the card prices from the Steam market
def updateData(specific=""):
  consecutiveFailureThreshold = 10
  failures = 0

  if specific == '':
    print('updating data')
  con = sqlite3.connect('data.sqlite')
  cur = con.cursor()

  i = 0
  pages = 1
  while i < pages:
    failed = False
    if specific == '':
      print('page %d:' % (i + 1)) 

    # get the page - why 95 instead of 100? the results sometimes shift
    # every so slightly during their download
    url = 'http://steamcommunity.com/market/search/render/?query=trading'
    url += '%%20card%%20%s&start=%d&count=100' % (specific, (i * 95))
    contents = ''
    try:
      with urllib.request.urlopen(url, timeout=10) as s:
        contents = s.read()

    # timeout or error reaching site
    except:
      failed = True

    # decode contents
    if not failed:
      contents = contents.decode('utf-8', 'ignore')
      contents = contents.replace('\\/','/')

      # internal API failure or market down
      if "There was an error performing your search." in contents:
        failed = True

    # retry page if failed
    if failed:
      print('  page failed, waiting 5 minutes to retry...')
      failures += 1
      time.sleep(300)
      if failures == consecutiveFailureThreshold:
        print('too many failures, exiting...')
        exit()
      continue
    else:
      failures = 0

    if specific == '':
      print('  parsing')

    # get page count if first page
    if (i == 0 and specific == ""):
      pages = re.findall('"total_count":(\d+)', contents)[0]
      pages = int(math.ceil(float(pages) / 95))
      print('there are %d pages' % pages)

    # regex data out
    names = re.findall('market_listing_item_name".*?>(.*?)<', contents)
    games = re.findall('market_listing_game_name">(.*?)<', contents)
    urls = re.findall('/listings/(\d+/.*?)">', contents)
    prices = re.findall('&#36;(\d+.\d+)', contents)
    counts = re.findall('market_listing_num_listings_qty">(.*?)<', contents)

    # handle each match
    for j in range(len(names)):
      game = games[j]

      # skip emoticons etc
      if 'Trading Card' not in game:
        continue

      name = names[j]
      url = urls[j].replace('?filter=trading%20card','')
      price = float(prices[j])
      when = str(datetime.datetime.utcnow())
      listings = int(counts[j].replace(',', ''))

      # add the game to DB if new
      q = "INSERT OR IGNORE INTO games VALUES(?, ?)"
      cur.execute(q, (game, 0))

      # replace the card listing in DB with newest price
      q = "INSERT OR REPLACE INTO cards VALUES(?, ?, ?, ?, ?, ?)"
      cur.execute(q, (game, name, url, price, when, listings))

    # go to next page
    i += 1

  # save changes
  con.commit()
  con.close()

def getClasses(name, short):
  classes = ''
  if 'Foil Trading Card' in name:
    classes += ' foil'
  if short:
    classes += ' bad'
  return classes

################################################################################
# escapes a string for HTML output
def escape(s):
  s = html.escape(s)
  s = s.encode('ascii', 'xmlcharrefreplace')
  s = s.decode('ascii')
  return s

################################################################################
# generates the HTML
def generateSite():
  print('updating the site')
  o = open("template.html").read()

  con = sqlite3.connect('data.sqlite')
  cur = con.cursor()

  # running totals for all sets
  totalStandard = 0
  totalFoil = 0

  # insert most expensive card stats
  q = 'SELECT * FROM cards ORDER BY cost DESC LIMIT 1'
  cur.execute(q)
  a = cur.fetchone()
  o = o.replace('[EXPENSIVE-NAME]', escape(a[1]))
  listingsBase = 'http://steamcommunity.com/market/listings/'
  o = o.replace('[EXPENSIVE-URL]', (listingsBase + a[2]))
  o = o.replace('[EXPENSIVE-PRICE]', '$%.2f' % a[3])


  # build the table, get price of all sets
  table = '<table class="sortable">\n<tr><th>Game</th><th># Cards</th>'
  table += '<th>Set Price</th><th>Avg. Card Price</th>'
  table += '<th class="discount">"Discount"</th>'
  table += '<th class="listings">Listings</th></tr>\n'

  # query the card data
  q = "SELECT g.name"
  q += ", CASE WHEN g.count = COUNT(c.name) THEN SUM(c.cost)"
  q += " ELSE SUM(c.cost) * g.count / COUNT(c.name) END AS 'costforall'"
  q += ", g.count, COUNT(c.name), SUM(c.count)"
  q += " FROM games g"
  q += " INNER JOIN cards c on c.game = g.name"
  q += " GROUP BY g.name"
  q += " ORDER BY costforall asc;"
  cur.execute(q)
  a = cur.fetchall()

  searchBase = 'http://steamcommunity.com/market/search?q='

  # add row for each set
  for b in a:
    # print game name and link
    game = b[0]

    gameEnc = escape(game)
    gameEnc = gameEnc.replace('Foil Trading Card', '(Foil)')
    gameEnc = gameEnc.replace('Trading Card', '')

    gameSearchEnc = game.replace('&', '%26')
    gameSearchEnc = escape(gameSearchEnc)
    search = searchBase + '%22' + gameSearchEnc + '%22'

    table += '<tr class="%s">' % getClasses(game, (b[3] < b[2]))
    table += '<td>%s' % gameEnc
    table += ' <a target="_blank" href="%s">&rarr;</a></td>' % search

    # add game price to totals
    if 'Foil Trading Card' in game:
      totalFoil += b[1]
    else:
      totalStandard += b[1]

    # print card count, set price, and average card price
    table += '<td>%d</td>' % b[2]
    table += '<td>$%0.2f</td>' % b[1]
    avg = (b[1] / b[2])
    table += '<td>$%0.2f</td>' % avg

    # print discount
    discount = '&nbsp;'
    if 'Foil Trading Card' not in game and ('Steam Summer Getaway' not in game):
      discount = '$%0.2f' % (avg * 0.85 * math.ceil(float(b[2]) / 2))
    table += '<td class="discount">%s</td>' % discount
    
    # print listings
    listings = '&nbsp;'
    if b[4] != None and b[4] > b[2]:
      listings = '{:,}'.format(b[4])
    table += '<td class="listings">%s</td>' % listings
    table += '</tr>\n'
    
  table += '</tbody></table>'

  o = o.replace('[TABLE]', table)

  # swap stats into HTML
  t = time.strftime('%Y-%m-%d %H:%M', time.gmtime()) + " GMT"
  o = o.replace('[TIME]', t)

  # get total games
  q = "SELECT COUNT(*) FROM games WHERE name NOT LIKE '%Foil Trading Card%'"
  cur.execute(q)
  a = cur.fetchone()
  o = o.replace('[GAME-COUNT]', str(a[0]))

  # get totals
  o = o.replace('[TOTAL-S]', "${:,.2f}".format(totalStandard))
  o = o.replace('[TOTAL-F]', "~${:,.2f}".format(totalFoil))
  o = o.replace('[TOTAL]', "~${:,.2f}".format(totalFoil + totalStandard * 5))

  # get median prices
  q = "SELECT cost"
  q += " FROM (SELECT * FROM cards"
  q += " WHERE game NOT LIKE '%Foil Trading Card%') AS nf"
  q += " ORDER BY cost LIMIT 1"
  q += " OFFSET (SELECT COUNT(*) FROM ("
  q += "SELECT * FROM cards WHERE game NOT LIKE '%Foil Trading Card%') AS nf" 
  q += ") / 2"

  cur.execute(q)
  a = cur.fetchone()
  o = o.replace('[MEDIAN-STANDARD-PRICE]', "${:,.2f}".format(a[0]))

  cur.execute(q.replace('NOT LIKE', 'LIKE'))
  a = cur.fetchone()
  o = o.replace('[MEDIAN-FOIL-PRICE]', "${:,.2f}".format(a[0]))

  # finish up
  con.close()
  f = open('index.html', 'w')
  f.write(o)
  f.close()

################################################################################
# updates the total card counts as info is available
def fixCounts():
  print('updating set counts')

  con = sqlite3.connect('data.sqlite')
  cur = con.cursor()

  # selects specified number of cards for a game and also the current count
  # of cards
  q = "SELECT g.name, g.count, COUNT(c.url) FROM games g"
  q += " INNER JOIN cards c ON c.game = g.name"
  q += " WHERE g.name NOT LIKE '%Foil Trading Card%'"
  q += " GROUP BY g.name"
  cur.execute(q)
  a = cur.fetchall()
  for b in a:
    game = b[0]
    target = b[1]
    counted = b[2]

    q = "UPDATE games SET count = ? WHERE name = ?"
    cur.execute(q, (counted, game))
    target = counted

    # copy standard set counts to foil sets
    game = game.replace('Trading Card', 'Foil Trading Card')
    q = "INSERT OR REPLACE INTO games VALUES(?, ?)"
    cur.execute(q, (game, target))

  con.commit()
  con.close()

################################################################################
# commits via git
def upload():
  print('uploading')

  os.system('git commit -a -m "automatic update"')
  os.system('git push')

################################################################################
# Program entrypoint.
if __name__ == "__main__":
  updateData()   if '-noupdate'   not in sys.argv else ''
  fixCounts()    if '-nofix'      not in sys.argv else ''
  generateSite() if '-nogenerate' not in sys.argv else ''
  upload()       if '-noupload'   not in sys.argv else ''
