#!/usr/bin/python
# -*- coding: utf-8 -*-

'''
    Kodi Helper Module for accessing TheTvDb API
    Includes the most common actions including a few special ones for Kodi use
    Full series and episode data is mapped into Kodi compatible format
'''
import requests
from requests.packages.urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import xbmc, xbmcgui, xbmcaddon
import re, os
from datetime import timedelta, date
from operator import itemgetter
import datetime
try:
    import simplejson as json
except ImportError:
    import json
from simplecache import use_cache, SimpleCache
import arrow

#set some parameters to the requests module
requests.packages.urllib3.disable_warnings()
SES = requests.Session()
RETRIES = Retry(total=5, backoff_factor=2, status_forcelist=[ 500, 502, 503, 504 ])
SES.mount('http://', HTTPAdapter(max_retries=RETRIES))
SES.mount('https://', HTTPAdapter(max_retries=RETRIES))

ADDON_ID = "script.module.thetvdb"
KODI_LANGUAGE = xbmc.getLanguage(xbmc.ISO_639_1)

class TheTvDb(object):
    '''Our main class'''
    days_ahead = 120
    win = None
    addon = None
    api_key = 'A7613F5C1482A540'

    def __init__(self):
        '''Initialize our Module'''

        self.cache = SimpleCache()
        self.win = xbmcgui.Window(10000)
        self.addon = xbmcaddon.Addon(ADDON_ID)
        self.log_msg("Initialized")

    def close(self):
        '''Cleanup Kodi cpython classes'''
        self.cache.close()
        del self.win
        del self.addon
        self.log_msg("Exited")

    @use_cache(2)
    def get_data(self, endpoint, prefer_localized=False):
        '''grab the results from the api'''
        url = 'https://api.thetvdb.com/' + endpoint
        headers = {'Content-Type': 'application/json',
                    'Accept': 'application/json',
            'User-agent': 'Mozilla/5.0', 'Authorization': 'Bearer %s' % self.get_token()}
        if prefer_localized:
            headers["Accept-Language"] = KODI_LANGUAGE
        response = requests.get(url, headers=headers, timeout=20)
        data = {}
        if response and response.content and response.status_code == 200:
            data = json.loads(response.content.decode('utf-8','replace'))
        elif response.status_code == 401:
            #token expired, refresh it and repeat our request
            headers['Bearer'] = self.get_token(True)
            response = requests.get(url, headers=headers, timeout=5)
            if response and response.content and response.status_code == 200:
                data = json.loads(response.content.decode('utf-8','replace'))
        if data.get("data"):
            data = data["data"]
        return data

    @use_cache(60)
    def get_series_posters(self, seriesid, season=None):
        '''retrieves the URL for the series poster, prefer season poster if season number provided'''
        if season:
            images = self.get_data("series/%s/images/query?keyType=season&subKey=%s" %(seriesid,season))
        else:
            images = self.get_data("series/%s/images/query?keyType=poster" %(seriesid))
        return self.process_images(images)

    @use_cache(60)
    def get_series_fanarts(self, seriesid, landscape=False):
        '''retrieves the URL for the series fanart image'''
        if landscape:
            images = self.get_data("series/%s/images/query?keyType=fanart&subKey=text" %(seriesid))
        else:
            images = self.get_data("series/%s/images/query?keyType=fanart&subKey=graphical" %(seriesid))
        return self.process_images(images)

    @staticmethod
    def process_images(images):
        '''helper to sort and correct the images as the api output is rather messy'''
        result = []
        if images:
            for image in images:
                if image["fileName"] and not image["fileName"].endswith("/"):
                    if not image["fileName"].startswith("http://"):
                        image["fileName"] = "http://thetvdb.com/banners/" + image["fileName"]
                    image_score = image["ratingsInfo"]["average"] * image["ratingsInfo"]["count"]
                    image["score"] = image_score
                    result.append(image)
        return [item["fileName"] for item in sorted(result,key=itemgetter("score"),reverse=True)]

    @use_cache(7)
    def get_episode(self, episodeid, seriesdetails=None):
        '''
            Returns the full information for a given episode id.
            Usage: specify the episode ID: TheTvDb().get_episode(episodeid)
        '''
        episode = self.get_data("episodes/%s" %episodeid, True)
        #we prefer localized content but if that fails, fallback to default
        if not episode.get("overview"):
            episode = self.get_data("episodes/%s" %episodeid)
        return self.map_episode_data(episode, seriesdetails)

    @use_cache(14)
    def get_series(self, seriesid):
        '''
            Returns a series record that contains all information known about a particular series id.
            Usage: specify the serie ID: TheTvDb().get_series(seriesid)
        '''
        seriesinfo = self.get_data("series/%s" %seriesid, True)
        #we prefer localized content but if that fails, fallback to default
        if not seriesinfo.get("overview"):
            seriesinfo = self.get_data("series/%s" %seriesid)
        return self.map_series_data(seriesinfo)

    @use_cache(7)
    def get_series_by_imdb_id(self, imdbid=""):
        '''get full series details by providing an imdbid'''
        items = self.get_data("search/series?imdbId=%s" %imdbid )
        if items:
            return self.get_series(items[0]["id"])
        else:
            return {}

    @use_cache(7)
    def get_continuing_series(self):
        '''
            only gets the continuing series,
            based on which series were recently updated as there is no other api call to get that information
        '''
        recent_series = self.get_recently_updated_series()
        continuing_series = []
        for recent_serie in recent_series:
            seriesinfo = self.get_series(recent_serie["id"])
            if seriesinfo and seriesinfo.get("status","") == "Continuing":
                continuing_series.append(seriesinfo)
        return continuing_series

    @use_cache(60)
    def get_series_actors(self, seriesid):
        '''
            Returns actors for the given series id.
            Usage: specify the series ID: TheTvDb().get_series_actors(seriesid)
        '''
        return self.get_data("series/%s/actors" %seriesid)

    @use_cache(30)
    def get_series_episodes(self, seriesid):
        '''
            Returns all episodes for a given series.
            Usage: specify the series ID: TheTvDb().get_series_episodes(seriesid)
            Note: output is only summary of episode details (non kodi formatted)
        '''
        all_episodes = []
        page = 1
        while True:
            #get all episodes by iterating over the pages
            data = self.get_data("series/%s/episodes?page=%s" %(seriesid,page) )
            if not data:
                break
            else:
                all_episodes += data
                page += 1
        return all_episodes

    def get_last_season_for_series(self, seriesid):
        '''get the last season for the series'''
        highest_season = 0
        summary = self.get_series_episodes_summary(seriesid)
        if summary:
            for season in summary["airedSeasons"]:
                if int(season) > highest_season:
                    highest_season = int(season)
        return highest_season

    def get_last_episode_for_series(self, seriesid):
        '''
            Returns the last aired episode for a given series
            Usage: specify the series ID: TheTvDb().get_last_episode_for_series(seriesid)
        '''
        summary = self.get_series_episodes_summary(seriesid)
        #somehow the absolutenumber is broken in the api so we have to get this info the hard way
        highest_season = self.get_last_season_for_series(seriesid)
        while not highest_season == -1:
            season_episodes = self.get_series_episodes_by_query(seriesid, "airedSeason=%s"%highest_season)
            season_episodes = sorted(season_episodes, key=lambda k: k.get('airedEpisodeNumber', 0), reverse=True)
            highest_eps = (datetime.datetime.strptime("1970-01-01","%Y-%m-%d").date(), 0)
            if season_episodes:
                for episode in season_episodes:
                    if episode["firstAired"]:
                        airdate = datetime.datetime.strptime(episode["firstAired"],"%Y-%m-%d").date()
                        if (airdate <= date.today()) and (airdate > highest_eps[0]):
                            highest_eps = (airdate, episode["id"])
                if highest_eps[1] != 0:
                    return self.get_episode(highest_eps[1])
            #go down one season untill we reach a match (there may be already announced seasons in the seasons list)
            highest_season -= 1
        self.log_msg("No last episodes found for series %s" %seriesid)
        return None

    @use_cache(7)
    def get_series_episodes_by_query(self, seriesid, query=""):
        '''
            This route allows the user to query against episodes for the given series.
            The response is an array of episode records that have been filtered down to basic information.
            Usage: specify the series ID: TheTvDb().get_series_episodes_by_query(seriesid)
            You must specify one or more fields for the query (combine multiple with &):
            absolutenumber=X --> Absolute number of the episode
            airedseason=X --> Aired season number
            airedepisode=X --> Aired episode number
            dvdseason=X --> DVD season number
            dvdepisode=X --> DVD episode number
            imdbid=X --> IMDB id of the series
            Note: output is only summary of episode details (non kodi formatted)
        '''
        all_episodes = []
        page = 1
        while True:
            #get all episodes by iterating over the pages
            data = self.get_data("series/%s/episodes/query?%s&page=%s"%(seriesid,query,page) )
            if not data:
                break
            else:
                all_episodes += data
                page += 1
        return all_episodes

    @use_cache(14)
    def get_series_episodes_summary(self, seriesid):
        '''
            Returns a summary of the episodes and seasons available for the series.
            Note: Season 0 is for all episodes that are considered to be specials.

            Usage: specify the series ID: TheTvDb().get_series_episodes_summary(seriesid)
        '''
        return self.get_data("series/%s/episodes/summary" %(seriesid))

    @use_cache(30)
    def search_series(self, query="", prefer_localized=False):
        '''
            Allows the user to search for a series based the name.
            Returns an array of results that match the query.
            Usage: specify the series ID: TheTvDb().search_series(searchphrase)

            Available parameter:
            prefer_localized --> True if you want to set the current kodi language as preferred in the results
        '''
        return self.get_data("search/series?name=%s" %query, prefer_localized )

    @use_cache(7)
    def get_recently_updated_series(self):
        '''
            Returns all series that have been updated in the last week
        '''
        day = 24*60*60
        utc_date = date.today() - timedelta(days=7)
        cur_epoch = (utc_date.toordinal() - date(1970, 1, 1).toordinal()) * day
        return self.get_data("updated/query?fromTime=%s" %cur_epoch)

    def get_unaired_episodes(self, seriesid):
        '''
            Returns the unaired episodes for the specified seriesid
            Usage: specify the series ID: TheTvDb().get_unaired_episodes(seriesid)
        '''
        next_episodes = []
        seriesinfo = self.get_series(seriesid)
        if seriesinfo and seriesinfo.get("status","") == "Continuing":
            highest_season = self.get_last_season_for_series(seriesid)
            episodes = self.get_series_episodes_by_query(seriesid, "airedSeason=%s"%highest_season)
            episodes = sorted(episodes, key=lambda k: k.get('airedEpisodeNumber', 0))
            for episode in episodes:
                if episode["firstAired"] and episode["episodeName"]:
                    airdate = datetime.datetime.strptime(episode["firstAired"],"%Y-%m-%d").date()
                    if airdate > date.today() and (airdate < (date.today() + timedelta(days=self.days_ahead))):
                        #if airdate is today or (max X days) in the future add to our list
                        episode = self.get_episode(episode["id"], seriesinfo)
                        next_episodes.append(episode)
        #return our list sorted by episode
        return sorted(next_episodes, key=lambda k: k.get('episode', ""))

    def get_nextaired_episode(self, seriesid):
        '''
            Returns the first next airing episode for the specified seriesid
            Usage: specify the series ID: TheTvDb().get_nextaired_episode(seriesid)
        '''
        next_episodes = self.get_unaired_episodes(seriesid)
        if next_episodes:
            return next_episodes[0]
        else:
            return None

    def get_unaired_episode_list(self, seriesids):
        '''
            Returns the next airing episode for each specified seriesid
            Usage: specify the series ID: TheTvDb().get_nextaired_episode(list of seriesids)
        '''
        next_episodes = []
        for seriesid in seriesids:
            episodes = self.get_unaired_episodes(seriesid)
            if episodes and episodes[0] != None:
                next_episodes.append(episodes[0])
        #return our list sorted by date
        return sorted(next_episodes, key=lambda k: k.get('firstAired', ""))

    def get_continuing_kodi_series(self):
        '''iterates all tvshows in the kodi library to find returning series'''
        kodi_series = self.get_kodi_json('VideoLibrary.GetTvShows',
            '{"properties": [ "title","imdbnumber","art", "genre", "cast", "studio" ] }')
        cont_series = []
        if kodi_series and kodi_series.get("tvshows"):
            for kodi_serie in kodi_series["tvshows"]:
                tvdb_details = None
                if kodi_serie["imdbnumber"] and kodi_serie["imdbnumber"].startswith("tt"):
                    #lookup serie by imdbid
                    tvdb_details = self.get_series_by_imdb_id(kodi_serie["imdbnumber"])
                elif kodi_serie["imdbnumber"]:
                    #imdbid in kodidb is already tvdb id
                    tvdb_details = self.get_series(kodi_serie["imdbnumber"])
                if not tvdb_details:
                    #lookup series id by name
                    result = self.search_series(name=kodi_serie["title"])
                    if result:
                        tvdb_details = result[0]
                if tvdb_details and tvdb_details["status"] == "Continuing":
                    kodi_serie["tvdb_id"] = tvdb_details["tvdb_id"]
                    cont_series.append(kodi_serie)
        return cont_series

    def get_kodi_unaired_episodes(self, single_episode_per_show=True):
        '''
            Returns the next unaired episode for all continuing tv shows in the Kodi library
            Defaults to a single episode (next unaired) for each show, to disable have False as argument.
        '''
        kodi_series = self.get_continuing_kodi_series()
        next_episodes = []
        for kodi_serie in kodi_series:
            serieid = kodi_serie["tvdb_id"]
            if single_episode_per_show:
                episodes = [ self.get_nextaired_episode(serieid) ]
            else:
                episodes = self.get_unaired_episodes(serieid)
            for next_episode in episodes:
                if next_episode:
                    #make the json output kodi compatible
                    next_episodes.append( self.map_kodi_data(kodi_serie,next_episode) )
        #return our list sorted by date
        return sorted(next_episodes, key=lambda k: k.get('firstaired', ""))

    def map_episode_data(self, episode_details, seriesdetails=None):
        '''maps full episode data from tvdb to kodi compatible format'''
        result = {}
        result["art"] = {}
        if episode_details["filename"]:
            result["art"]["thumb"] = "http://thetvdb.com/banners/" + episode_details["filename"]
            result["thumbnail"] = result["art"]["thumb"]
        result["art"] = {}
        result["title"] = episode_details["episodeName"]
        result["label"] = "%sx%s. %s" %(episode_details["airedSeason"],
            episode_details["airedEpisodeNumber"],episode_details["episodeName"])
        result["season"] = episode_details["airedSeason"]
        result["episode"] = episode_details["airedEpisodeNumber"]
        result["firstaired"] = episode_details["firstAired"]
        result["writer"] = episode_details["writers"]
        result["director"] = episode_details["directors"]
        result["gueststars"] = episode_details["guestStars"]
        result["rating"] = episode_details["siteRating"]
        result["plot"] = episode_details["overview"]
        result["airdate"] = self.get_local_date(episode_details["firstAired"])
        result["airdate.label"] = "%s (%s)" %(result["label"], result["airdate"])
        #append seriesinfo to details if provided
        if seriesdetails:
            result["tvshowtitle"] = seriesdetails["title"]
            result["showtitle"] = seriesdetails["title"]
            result["network"] = seriesdetails["network"]
            result["studio"] = seriesdetails["studio"]
            result["genre"] = seriesdetails["genre"]
            result["airtime"] = seriesdetails["airtime"]
            result["airdatetime"] = "%s %s" %(result["airdate"], result["airtime"])
            result["airdatetime.label"] = "%s - %s %s" %(result["airdatetime"], 
                xbmc.getLocalizedString(145), result["network"])
            result["art"]["tvshow.poster"] = seriesdetails["art"].get("poster","")
            result["art"]["tvshow.landscape"] = seriesdetails["art"].get("landscape","")
            result["art"]["tvshow.fanart"] = seriesdetails["art"].get("fanart","")
            result["art"]["tvshow.banner"] = seriesdetails["art"].get("banner","")
            try:
                result["runtime"] = int(seriesdetails["runtime"]) * 60
            except Exception:
                pass
            season_posters = self.get_series_posters(episode_details["seriesId"],episode_details["airedSeason"])
            if season_posters:
                result["art"]["season.poster"] = season_posters[0]
        return result
        
    @staticmethod
    def map_kodi_data(kodi_tv_show_details, episode_details):
        '''combine kodi tvshow details with episode details'''
        result = episode_details
        result["art"]["tvshow.poster"] = kodi_tv_show_details["art"].get("poster","")
        result["art"]["season.poster"] = episode_details.get("season.poster","")
        result["art"]["tvshow.landscape"] = kodi_tv_show_details["art"].get("landscape","")
        result["art"]["tvshow.fanart"] = kodi_tv_show_details["art"].get("fanart","")
        result["art"]["tvshow.banner"] = kodi_tv_show_details["art"].get("banner","")
        result["art"]["tvshow.clearlogo"] = kodi_tv_show_details["art"].get("clearlogo","")
        result["art"]["tvshow.clearart"] = kodi_tv_show_details["art"].get("clearart","")
        result["tvshowtitle"] = kodi_tv_show_details["title"]
        result["showtitle"] = kodi_tv_show_details["title"]
        result["studio"] = kodi_tv_show_details["studio"]
        result["genre"] = kodi_tv_show_details["genre"]
        result["cast"] = kodi_tv_show_details["cast"]
        #result["tvshowid"] = kodi_tv_show_details["tvshowid"]
        result["episodeid"] = -1
        result["file"] = "videodb://tvshows/titles/%s/" %kodi_tv_show_details["tvshowid"]
        result["type"] = "episode"
        result["DBTYPE"] = "episode"
        result["isFolder"] = True
        return result

    def map_series_data(self, showdetails):
        '''maps the tvdb data to more kodi compatible format'''
        result = {}
        if showdetails:
            result["title"] = showdetails["seriesName"]
            result["status"] = showdetails["status"]
            result["tvdb_id"] = showdetails["id"]
            result["network"] = showdetails["network"]
            result["studio"] = [showdetails["network"]]
            result["airday"] = self.get_local_weekday(showdetails["airsDayOfWeek"])
            result["airday.short"] = self.get_local_weekday(showdetails["airsDayOfWeek"],True)
            result["airtime"] = self.get_local_time(showdetails["airsTime"])
            result["airdaytime"] = "%s %s (%s)" %(result["airday"], result["airtime"], result["network"])
            result["airdaytime.short"] = "%s %s" %(result["airday.short"], result["airtime"])
            result["airdaytime.label"] = "%s %s - %s %s" %(result["airday"], result["airtime"], xbmc.getLocalizedString(145), result["network"])
            result["airdaytime.label.short"] = "%s %s - %s %s" %(result["airday.short"], result["airtime"], xbmc.getLocalizedString(145), result["network"])
            result["rating"] = showdetails["siteRating"]
            result["votes"] = showdetails["siteRatingCount"]
            result["rating.tvdb"] = showdetails["siteRating"]
            result["votes.tvdb"] = showdetails["siteRatingCount"]
            try:
                result["runtime"] = int(showdetails["runtime"]) * 60
            except Exception:
                pass
            result["plot"] = showdetails["overview"]
            result["genre"] = showdetails["genre"]
            result["firstaired"] = showdetails["firstAired"]
            result["imdbnumber"] = showdetails["imdbId"]
            #artwork
            result["art"] = {}
            fanarts = self.get_series_fanarts(showdetails["id"])
            if fanarts:
                result["art"]["fanart"] = fanarts[0]
                result["art"]["fanarts"] = fanarts
            landscapes = self.get_series_fanarts(showdetails["id"], True)
            if landscapes:
                result["art"]["landscapes"] = landscapes
                result["art"]["landscape"] = landscapes[0]
            posters = self.get_series_posters(showdetails["id"])
            if posters:
                result["art"]["posters"] = posters
                result["art"]["poster"] = posters[0]
            if showdetails.get("banner"):
                result["art"]["banner"] = "http://thetvdb.com/banners/" + showdetails["banner"]
        return result

    @staticmethod
    def log_msg(msg, level=xbmc.LOGDEBUG):
        '''logger to kodi log'''
        if isinstance(msg,unicode):
            msg = msg.encode("utf-8")
        xbmc.log('{0} --> {1}'.format(ADDON_ID, msg), level=level)

    def get_token(self, refresh=False):
        '''get jwt token for api'''
        #get token from memory cache first
        token = self.win.getProperty("script.module.thetvdb.token").decode('utf-8')
        if token and not refresh:
            return token

        #refresh previous token
        prev_token = self.addon.getSetting("token")
        if prev_token:
            url = 'https://api.thetvdb.com/refresh_token'
            headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
                'User-agent': 'Mozilla/5.0', 'Authorization': 'Bearer %s' % prev_token}
            response = requests.get(url, headers=headers)
            if response and response.content and response.status_code == 200:
                data = json.loads(response.content.decode('utf-8','replace'))
                token = data["token"]
            if token:
                self.win.setProperty("script.module.thetvdb.token",token)
                return token

        #do first login to get initial token
        url = 'https://api.thetvdb.com/login'
        payload = {'apikey': self.api_key}
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'User-agent': 'Mozilla/5.0'}
        response = requests.post(url, data=json.dumps(payload), headers=headers)
        if response and response.content and response.status_code == 200:
            data = json.loads(response.content.decode('utf-8','replace'))
            token = data["token"]
            self.addon.setSetting("token",token)
            self.win.setProperty("script.module.thetvdb.token",token)
            return token
        else:
            self.log_msg("Error getting JWT token!")
            return None

    @staticmethod
    def get_kodi_json(method,params):
        '''helper to get data from the kodi json database'''
        json_response = xbmc.executeJSONRPC('{ "jsonrpc": "2.0", "method" : "%s", "params": %s, "id":1 }'
            %(method, params.encode("utf-8")))
        jsonobject = json.loads(json_response.decode('utf-8','replace'))
        if jsonobject.has_key('result'):
            jsonobject = jsonobject['result']
        return jsonobject
        
    @staticmethod
    def get_local_time(timestr):
        '''returns the correct localized representation of the time provided by the api'''
        result = ""
        if timestr:
            timestr = timestr.replace(".",":")
            if "H" in xbmc.getRegion('time'):
                time_format = "HH:mm"
            else:
                time_format = "h:mm A"
            if "AM" in timestr or "PM" in timestr:
                result = arrow.get(timestr, 'h:mm A').format( time_format,locale=KODI_LANGUAGE )
            elif "am" in timestr or "pm" in timestr:
                result = arrow.get(timestr, 'h:mm a').format( time_format,locale=KODI_LANGUAGE )
            else:
                result = arrow.get(timestr, 'HH:mm').format( time_format,locale=KODI_LANGUAGE )
        return result
        
    @staticmethod
    def get_local_date(datestr):
        '''returns the localized representation of the date provided by the api'''
        if not datestr:
            return datestr
        return arrow.get(datestr).strftime(xbmc.getRegion('dateshort'))

    @staticmethod
    def get_local_weekday(weekday, short=False):
        '''returns the localized representation of the weekday provided by the api'''
        if not weekday:
            return weekday
        elif short:
            return arrow.get(weekday,'dddd').format( 'ddd',locale=KODI_LANGUAGE ).capitalize()
        else:
            return arrow.get(weekday,'dddd').format( 'dddd',locale=KODI_LANGUAGE ).capitalize()
