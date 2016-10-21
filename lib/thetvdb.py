# -*- coding: utf-8 -*-
import requests
from requests.packages.urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import xbmc, xbmcgui, xbmcaddon
import time, re, os
from datetime import timedelta, date
import datetime
try:
    import simplejson as json
except ImportError:
    import json
from simplecache import SimpleCache, use_cache

#set some parameters to the requests module
requests.packages.urllib3.disable_warnings()
s = requests.Session()
retries = Retry(total=5, backoff_factor=2, status_forcelist=[ 500, 502, 503, 504 ])
s.mount('http://', HTTPAdapter(max_retries=retries))
s.mount('https://', HTTPAdapter(max_retries=retries))

ADDON_ID = "script.module.thetvdb"
KODI_LANGUAGE = xbmc.getLanguage(xbmc.ISO_639_1)

class TheTvDb(object):

    days_ahead = 60
    win = None
    kodi_addon = None
    
    def __init__(self):
        '''Initialize our Module'''
        self.cache = SimpleCache()
        self.log_msg("Initialized")
        self.win = xbmcgui.Window(10000)
        self.kodi_addon = xbmcaddon.Addon(self.kodi_addon_ID)
        
    def __del__(self):
        '''Cleanup Kodi cpython classes'''
        del self.win
        del self.kodi_addon
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
    def get_series_poster(self, seriesid,season=None):
        '''retrieves the URL for the series poster, prefer season poster if season number provided'''
        score = 0
        posterurl = ""
        if season:
            images = self.get_data("series/%s/images/query?keyType=season&subKey=%s" %(seriesid,season))
            for image in images:
                image_score = image["ratingsInfo"]["average"] * image["ratingsInfo"]["count"]
                if image_score > score:
                    posterurl = "http://thetvdb.com/banners/" + image["fileName"]
                    score = image_score

        if not posterurl:
            images = self.get_data("series/%s/images/query?keyType=poster" %(seriesid))
            for image in images:
                image_score = image["ratingsInfo"]["average"] * image["ratingsInfo"]["count"]
                if image_score > score:
                    posterurl = "http://thetvdb.com/banners/" + image["fileName"]
                    score = image_score
        return posterurl

    @use_cache(60)
    def get_series_fanart(self, seriesid,Landscape=False):
        '''retrieves the URL for the series fanart image'''
        score = 0
        fanarturl = ""
        images = self.get_data("series/%s/images/query?keyType=fanart" %(seriesid))
        for image in images:
            if (image["subKey"] == "text" and Landscape) or (
                not Landscape and image["subKey"] == "graphical"):
                image_score = image["ratingsInfo"]["average"] * image["ratingsInfo"]["count"]
                if image_score > score:
                    fanarturl = "http://thetvdb.com/banners/" + image["fileName"]
                    score = image_score

        return fanarturl

    @use_cache(7)
    def get_episode(self, episodeid):
        '''
            Returns the full information for a given episode id.
            Usage: specify the episode ID: TheTvDb().get_episode(episodeid)
        '''
        episode = self.get_data("episodes/%s" %episodeid)
        if episode["filename"]:
            episode["thumbnail"] = "http://thetvdb.com/banners/" + episode["filename"]
        episode["poster"] = self.get_series_poster(episode["seriesId"],episode["airedSeason"])
        return episode

    @use_cache(60)
    def get_series(self, seriesid,ContinuingOnly=False):
        '''
            Returns a series record that contains all information known about a particular series id.
            Usage: specify the serie ID: TheTvDb().get_series(seriesid)
        '''
        seriesinfo = self.get_data("series/%s" %seriesid, True)
        if ContinuingOnly and seriesinfo.get("status","") != "Continuing":
            return None
        #we prefer localized content but if that fails, fallback to default
        if not seriesinfo.get("overview"):
            seriesinfo = self.get_data("series/%s" %seriesid)
        return self.map_data(seriesinfo)
    
    @use_cache(60)
    def get_series_by_imdb_id(self, imdbid=""):
        '''get full series details by providing an imdbid'''
        items = self.search_series(imdbid=imdbid)
        return self.get_series(items[0]["id"]) if items else None
        
    @use_cache(30)
    def get_continuing_series(self):
        '''
            only gets the continuing series, 
            based on which series were recently updated as there is no other api call to get that information
        '''
        recent_series = self.get_recently_updated_series()
        continuing_series = []
        for recent_serie in recent_series:
            seriesinfo = self.get_series(recent_serie["id"],True)
            if seriesinfo:
                continuing_series.append(seriesinfo)
        return continuing_series

    @use_cache(60)
    def get_series_actors(self, seriesid):
        '''
            Returns actors for the given series id.
            Usage: specify the series ID: TheTvDb().get_series_actors(seriesid)
        '''
        return self.get_data("series/%s/actors" %seriesid)

    @use_cache(60)
    def get_series_episodes(self, seriesid):
        '''
            Returns all episodes for a given series.
            Usage: specify the series ID: TheTvDb().get_series_episodes(seriesid)
        '''
        allepisodes = []
        page = 1
        while True:
            #get all episodes by iterating over the pages
            data = self.get_data("series/%s/episodes?page=%s" %(seriesid,page) )
            if not data:
                break
            else:
                allepisodes += data
                page += 1
        return allepisodes

    @use_cache(60)
    def get_last_episode_for_series(self, seriesid):
        '''
            Returns the last aired episode for a given series
            Usage: specify the series ID: TheTvDb().get_last_episode_for_series(seriesid)
        '''
        summary = self.get_series_episodes_summary(seriesid)
        #somehow the absolutenumber is broken in the api so we have to get this info the hard way
        if summary:
            highest_season = 0
            for season in summary["airedSeasons"]:
                if int(season) > highest_season:
                    highest_season = int(season)
            season_episodes = self.get_series_episodes_by_query(seriesid, "airedSeason=%s"%highest_season)
            highest_eps = (datetime.datetime.strptime("1970-01-01","%Y-%m-%d").date(), 0)
            if season_episodes:
                for episode in season_episodes:
                    if episode["firstAired"]:
                        airdate = datetime.datetime.strptime(episode["firstAired"],"%Y-%m-%d").date()
                        if airdate <= date.today() and airdate > highest_eps[0]:
                            highest_eps = (airdate, episode["id"])
                if highest_eps[1] != 0:
                    return self.get_episode(highest_eps[1])
        return None

    @use_cache(7)
    def get_series_episodes_by_query(self, seriesid, query="absoluteNumber=&airedSeason=&airedEpisode=&dvdSeason=&dvdEpisode=&imdbId=%s"):
        '''
            This route allows the user to query against episodes for the given series. 
            The response is an array of episode records that have been filtered down to basic information.
            Usage: specify the series ID: TheTvDb().get_series_episodes_by_query(seriesid)
            optionally you can specify one or more fields for the query:
            absolutenumber --> Absolute number of the episode
            airedseason --> Aired season number
            airedepisode --> Aired episode number
            dvdseason --> DVD season number
            dvdepisode --> DVD episode number
            imdbid --> IMDB id of the series
        '''
        allepisodes = []
        page = 1
        while True:
            #get all episodes by iterating over the pages
            data = self.get_data("series/%s/episodes/query?%s&page=%s"%(seriesid,query,page) )
            if not data:
                break
            else:
                allepisodes += data
                page += 1
        return allepisodes

    @use_cache(30)
    def get_series_episodes_summary(self, seriesid):
        '''
            Returns a summary of the episodes and seasons available for the series.
            Note: Season 0 is for all episodes that are considered to be specials.

            Usage: specify the series ID: TheTvDb().get_series_episodes_summary(seriesid)
        '''
        return self.get_data("series/%s/episodes/summary" %(seriesid))

    @use_cache(30)
    def search_series(self, name="",imdbid="",zap2itid="", prefer_localized=False):
        '''
            Allows the user to search for a series based on one or more parameters. Returns an array of results that match the query.
            Usage: specify the series ID: TheTvDb().search_series(parameters)

            Available parameters:
            name --> Name of the series to search for.
            imdbid --> IMDB id of the series
            zap2itid -->  Zap2it ID of the series to search for.
            prefer_localized --> True if you want to set the current kodi language as preferred in the results
        '''
        return self.get_data("search/series?name=%s&imdbId=%s&zap2itId=%s"
            %(name,imdbid,zap2itid),prefer_localized=prefer_localized )

    @use_cache(7)
    def get_recently_updated_series(self):
        '''
            Returns all series that have been updated in the last week
        '''
        DAY = 24*60*60
        utc_date = date.today() - timedelta(days=7)
        cur_epoch = (utc_date.toordinal() - date(1970, 1, 1).toordinal()) * DAY
        return self.get_data("updated/query?fromTime=%s" %cur_epoch)

    @use_cache(7)
    def get_unaired_episodes(self, seriesid):
        '''
            Returns the unaired episodes for the specified seriesid
            Usage: specify the series ID: TheTvDb().get_unaired_episodes(seriesid)
        '''
        next_episodes = []
        seriesinfo = self.get_series(seriesid, True)
        if seriesinfo:
            episodes = self.get_series_episodes(seriesid)
            for episode in episodes:
                if episode["firstAired"] and episode["episodeName"]:
                    airdate = datetime.datetime.strptime(episode["firstAired"],"%Y-%m-%d").date()
                    if airdate == date.today() or (
                        airdate > date.today() and airdate < (date.today() + timedelta(days=self.days_ahead)) ):
                        #if airdate is today or (max X days) in the future add to our list
                        episode = self.get_episode(episode["id"])
                        episode["seriesinfo"] = seriesinfo
                        next_episodes.append(episode)

        #return our list sorted by date
        return sorted(next_episodes, key=lambda k: k.get('firstAired', ""))

    @use_cache(7)
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

    @use_cache(7)
    def get_unaired_episode_list(self, seriesids):
        '''
            Returns the next airing episode for each specified seriesid
            Usage: specify the series ID: TheTvDb().get_nextaired_episode(list of seriesids)
        '''
        next_episodes = []
        for seriesid in seriesids:
            episodes = self.get_unaired_episodes(seriesid)
            if episodes:
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
                    result = self.search_series(imdbId=kodi_serie["imdbnumber"])
                    if result: 
                        tvdb_details = result[0]
                elif kodi_serie["imdbnumber"]:
                    #imdbid in kodidb is already tvdb id
                    tvdb_details = self.get_series(kodi_serie["imdbnumber"],True)
                if not tvdb_details:
                    #lookup series id by name
                    result = self.search_series(name=kodi_serie["title"])
                    if result: 
                        tvdb_details = search_serie[0]
                if tvdb_details and tvdb_details["status"] == "Continuing":
                    kodi_serie["tvdbid"] = tvdb_details["id"]
                    cont_series.append(kodi_serie)
        return cont_series

    def get_kodi_series_unaired_episodes_list(self, single_episode_per_show=True):
        '''
            Returns the next unaired episode for all continuing tv shows in the Kodi library
            Defaults to a single episode (next unaired) for each show, to disable have False as argument.
        '''
        kodi_series = self.get_continuing_kodi_series()
        next_episodes = []
        for kodi_serie in kodi_series:
            serieid = kodi_serie["tvdbid"]
            if single_episode_per_show:
                episodes = [ self.get_nextaired_episode(serieid) ]
            else:
                episodes = self.get_unaired_episodes(serieid)
            for next_episode in episodes:
                if next_episode:
                    #make the json output kodi compatible
                    next_episodes.append( self.map_kodi_episode_data(kodi_serie,next_episode) )
        #return our list sorted by date
        return sorted(next_episodes, key=lambda k: k.get('firstAired', ""))
        
    @staticmethod
    def map_kodi_episode_data(kodi_tv_show_details, episode_details):
        '''maps data from tvdb to kodi compatible format'''
        episode_details["art"] = {}
        episode_details["art"]["thumb"] = episode_details.get("thumbnail","")
        episode_details["art"]["poster"] = episode_details.get("poster","")
        episode_details["art"]["landscape"] = kodi_tv_show_details["art"].get("landscape",
            episode_details["seriesinfo"]["art"].get("landscape",""))
        episode_details["art"]["fanart"] = kodi_tv_show_details["art"].get("fanart",
            episode_details["seriesinfo"]["art"].get("fanart",""))
        episode_details["art"]["banner"] = kodi_tv_show_details["art"].get("banner",
            episode_details["seriesinfo"]["art"].get("banner",""))
        episode_details["art"]["clearlogo"] = kodi_tv_show_details["art"].get("clearlogo","")
        episode_details["art"]["clearart"] = kodi_tv_show_details["art"].get("clearart","")

        episode_details["title"] = episode_details["episodeName"]
        episode_details["label"] = "%sx%s. %s" %(episode_details["airedSeason"],
            episode_details["airedEpisodeNumber"],episode_details["episodeName"])
        episode_details["tvshowtitle"] = kodi_tv_show_details["title"]
        episode_details["studio"] = kodi_tv_show_details["studio"]
        episode_details["genre"] = kodi_tv_show_details["genre"]
        episode_details["cast"] = kodi_tv_show_details["cast"]
        episode_details["tvshowid"] = kodi_tv_show_details["tvshowid"]
        episode_details["season"] = episode_details["airedSeason"]
        episode_details["episode"] = episode_details["airedEpisodeNumber"]
        episode_details["episodeid"] = -1
        episode_details["file"] = "videodb://tvshows/titles/%s/" %kodi_tv_show_details["tvshowid"]
        episode_details["type"] = "episode"
        episode_details["DBTYPE"] = "episode"
        episode_details["firstaired"] = episode_details["firstAired"]
        episode_details["writer"] = episode_details["writers"]
        episode_details["director"] = [ episode_details["director"] ]
        episode_details["rating"] = episode_details["siteRating"]
        episode_details["plot"] = episode_details["overview"]
        episode_details["runtime"] = int(episode_details["seriesinfo"]["runtime"]) * 60
        episode_details["isFolder"] = True
        extraprops = {}
        extraprops["airday"] = episode_details["seriesinfo"]["airsDayOfWeek"] #todo: translate?
        extraprops["airtime"] = episode_details["seriesinfo"]["airsTime"] #todo: use regional formatting
        extraprops["DBTYPE"] = "episode"
        episode_details["extraproperties"] = extraprops
        return episode_details
        
    def map_data(self, showdetails):
        '''maps the tvdb data to more kodi compatible format'''
        result = {}
        if showdetails:
            result["title"] = showdetails["seriesName"]
            result["status"] = showdetails["status"]
            result["tvdb_id"] = showdetails["id"]
            result["network"] = showdetails["network"]
            result["studio"] = showdetails["network"]
            result["airsDayOfWeek"] = showdetails["airsDayOfWeek"]#TODO translate to regional format?
            result["airsTime"] = showdetails["airsTime"]#TODO translate to regional format?
            result["tvdb.rating"] = showdetails["siteRating"]
            result["tvdb.ratingcount"] = showdetails["siteRatingCount"]
            result["runtime"] = showdetails["runtime"]
            result["plot"] = showdetails["overview"]
            result["genre"] = showdetails["genre"]
            result["firstaired"] = showdetails["firstAired"]
            result["imdbnumber"] = showdetails["imdbId"]
            #artwork
            result["art"] = {}
            result["art"]["fanart"] = self.get_series_fanart(seriesid)
            result["art"]["poster"] = self.get_series_poster(seriesid)
            result["art"]["landscape"] = self.get_series_poster(seriesid,True)
            if showdetails.get("banner"):
                result["art"]["banner"] = "http://thetvdb.com/banners/" + showdetails["banner"]  
        return result
    
    @staticmethod
    def log_msg(msg):
        '''logger to kodi log'''
        if isinstance(msg,unicode):
            msg = msg.encode("utf-8")
        xbmc.log('{0} --> {1}'.format(self.kodi_addon_ID, msg))

    @staticmethod
    def get_token(refresh=False):
        '''get jwt token for api'''
        #get token from memory cache first
        token = self.win.getProperty("script.module.thetvdb.token").decode('utf-8')
        if token and not refresh:
            return token

        #refresh previous token
        prev_token = self.kodi_addon.getSetting("token")
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
        payload = {'apikey': 'A7613F5C1482A540'}
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'User-agent': 'Mozilla/5.0'}
        response = requests.post(url, data=json.dumps(payload), headers=headers)
        if response and response.content and response.status_code == 200:
            data = json.loads(response.content.decode('utf-8','replace'))
            token = data["token"]
            self.kodi_addon.setSetting("token",token)
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
        if(jsonobject.has_key('result')):
            jsonobject = jsonobject['result']
        return jsonobject
