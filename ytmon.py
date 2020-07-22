#!/usr/bin/env python3

"""
ytmon is a YouTube subscription emulator.

It monitors YouTube channels for new videos and stores them offline, to be used
in a media center or something else.
"""

from bs4 import BeautifulSoup
from lxml import etree
import argparse
import copy
import datetime
import feedparser
import functools
import json
import jsonschema
import os
import pathvalidate
import re
import requests
import shutil
import sys
import time
import youtube_dl

print = functools.partial(print, flush=True)

_DEBUG = False
_FEED_URLS = {}
_CONFIG_SCHEMA = {
    'type': 'object',
    'required': [
        'output_directory',
        'interval',
        'channels',
    ],
    'properties': {
        'output_directory': {
            'type': 'string',
            'minLength': 1,
        },
        'interval': {
            'type': 'integer',
            'minimum': 60,
        },
        'channels': {
            'type': 'array',
            'minItems': 1,
            'items': {
                'type': 'object',
                'required': [
                    'url',
                    'keep_days',
                ],
                'properties': {
                    'url': {
                        'type': 'string',
                        'pattern': r'^https?://(www\.)?youtube\.com\/(c|channel|user)\/[^/]+$',  # noqa
                    },
                    'keep_days': {
                        'type': 'integer',
                        'minimum': 1,
                    },
                },
            },
        },
        'youtube_dl_opts': {
            'type': 'object',
        },
        'permissions': {
            'type': 'object',
            'required': [
                'uid',
                'gid',
            ],
            'properties': {
                'uid': {
                    'type': 'integer',
                    'minimum': 0,
                    'maximum': 65535,
                },
                'gid': {
                    'type': 'integer',
                    'minimum': 0,
                    'maximum': 65535,
                },
            },
        },
        'jellyfin': {
            'type': 'object',
            'required': [
                'api_key',
                'host',
                'port',
                'path',
                'tls',
                'library_name',
            ],
            'properties': {
                'api_key': {
                    'type': 'string',
                    'pattern': '^[a-f0-9]{32}$',
                },
                'host': {
                    'type': 'string',
                    'minLength': 1,
                },
                'port': {
                    'type': 'integer',
                    'minimum': 1,
                    'maximum': 65535,
                },
                'path': {
                    'type': 'string',
                    'minLength': 1,
                },
                'tls': {
                    'type': 'boolean',
                },
                'library_name': {
                    'type': 'string',
                    'minLength': 1,
                },
            },
        }
    }
}


def _read_config(path):
    """
    Read the user's config file.

    :param str path: Path to config file.

    :return: A dict containing the config structure.
    """
    if _DEBUG:
        print('Reading config:', path)

    try:
        with open(path) as f:
            config = json.load(f)
    except (OSError, ValueError) as e:
        print('Failed to read config: {}'.format(e))
        sys.exit(1)

    try:
        jsonschema.validate(config, schema=_CONFIG_SCHEMA)
    except jsonschema.exceptions.ValidationError as e:
        print('Failed to validate config: {}'.format(e))
        sys.exit(1)

    return config


def _create_channel_directory(config, name):
    """
    Create a channel's output directory.

    :param dict config: Config dict.
    :param str name: Pre-sanitized channel name.

    :return: Boolean indication success of operation.
    """
    full = os.path.join(config['output_directory'], name)

    if os.path.isdir(full):
        return True

    if os.path.exists(full):
        print('{} exists but is not a directory'.format(full))
        return False

    if _DEBUG:
        print('Creating directory:', full)

    try:
        os.makedirs(full)
    except OSError as e:
        print('Failed to create directory {}: {}'.format(full, e))
        return False

    if 'permissions' in config:
        try:
            os.chown(
                full,
                config['permissions']['uid'],
                config['permissions']['gid']
            )
        except OSError as e:
            print('Failed to chown {}: {}'.format(full, e))

    return True


def _channel_to_feed(channel_url):
    """
    Determine the Atom feed URL from a channel URL.

    :param str channel_url: Channel URL.

    :return: Feed URL if found, else None.
    """
    if _DEBUG:
        print('Getting feed URL for channel:', channel_url)

    response = requests.get('{}/about'.format(channel_url))
    soup = BeautifulSoup(response.content, 'html.parser')
    links = soup.find('head').find_all('link')

    for link in links:
        if 'type' in link.attrs and \
                link.attrs['type'] == 'application/rss+xml':
            if _DEBUG:
                print('Feed URL:', link.attrs['href'])

            return link.attrs['href']

    print('Feed URL not found for channel:', channel_url)
    return None


def _download_feed(url):
    """
    Download an Atom feed.

    :param str url: Feed URL.

    :return: Parsed feed structure.
    """
    if _DEBUG:
        print('Downloading feed:', url)

    return feedparser.parse(url)


def _entry_to_path(config, feed, entry):
    """
    Determine the proper output path for an Atom feed entry.

    :param dict config: Config dict.
    :param feed: Parsed Atom feed structure.
    :param entry: Parsed Atom feed entry structure.

    :return: Path string.
    """
    channel_title = pathvalidate.sanitize_filename(feed.feed.title)

    return os.path.join(
        config['output_directory'],
        channel_title,
        '{} - {} [{}]'.format(
            entry.published.split('T')[0],
            pathvalidate.sanitize_filename(entry.title),
            entry.yt_videoid
        )
    )


def _write_nfo(config, feed, entry):
    """
    Write a Kodi/Emby/Jellyfin-compatible .nfo file for a video.

    :param dict config: Config dict.
    :param feed: Parsed Atom feed structure.
    :param entry: Parsed Atom feed entry structure.
    """
    if _DEBUG:
        print('Writing NFO for:', entry.title)

    movie = etree.Element('movie')
    title = etree.SubElement(movie, 'title')
    title.text = entry.title
    plot = etree.SubElement(movie, 'plot')
    plot.text = entry.summary
    premiered = etree.SubElement(movie, 'premiered')
    premiered.text = entry.published.split('T')[0],

    try:
        path = '{}.nfo'.format(_entry_to_path(config, feed, entry))
        with open(path, 'wb') as f:
            f.write(
                etree.tostring(
                    movie,
                    encoding='UTF-8',
                    standalone=True,
                    xml_declaration=True,
                    pretty_print=True
                )
            )
            f.write(b'\n')
    except (IOError, OSError) as e:
        print('Failed to write NFO file {}: {}'.format(path, e))

    if 'permissions' in config:
        try:
            os.chown(
                path,
                config['permissions']['uid'],
                config['permissions']['gid']
            )
        except OSError as e:
            print('Failed to chown {}: {}'.format(path, e))


def _download_entry(config, channel, feed, entry):
    """
    Download the video for an Atom feed entry, if necessary.

    :param dict config: Config dict.
    :param dict channel: Individual channel config.
    :param feed: Parsed Atom feed structure.
    :param entry: Parsed Atom feed entry structure.
    """
    if _DEBUG:
        print('Downloading entry:', entry.title)

    now = datetime.datetime.now(datetime.timezone.utc)
    delta = datetime.timedelta(days=channel['keep_days'])

    # if the video is too old, skip it
    published = datetime.datetime.fromisoformat(entry.published)
    if now - published > delta:
        if _DEBUG:
            print('Entry too old, skipping')

        return

    # if the video already exists, skip it
    path = '{}.mp4'.format(_entry_to_path(config, feed, entry))
    if os.path.isfile(path):
        if _DEBUG:
            print('Video already exists')

        return

    if not entry.links:
        if _DEBUG:
            print('Entry is missing links:', entry)

        return

    # use youtube_dl to download and convert the video
    url = entry.links[0].href
    opts = copy.deepcopy(config['youtube_dl_opts'])
    opts['outtmpl'] = path
    opts['quiet'] = not _DEBUG

    if _DEBUG:
        print('Running youtube_dl')

    try:
        with youtube_dl.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except youtube_dl.utils.YoutubeDLError as e:
        print('Failed to download {}: {}'.format(url, e))
        return

    if 'permissions' in config:
        try:
            os.chown(
                path,
                config['permissions']['uid'],
                config['permissions']['gid']
            )
        except OSError as e:
            print('Failed to chown {}: {}'.format(path, e))

    _write_nfo(config, feed, entry)
    return


def _download_channel(config, channel):
    """
    Download the videos video for an individual channel.

    :param dict config: Config dict.
    :param dict channel: Individual channel config.

    :return: Path-sanitized channel title.
    """
    url = channel['url']

    if _DEBUG:
        print('Downloading channel:', url)

    # determine the Atom feed URL if we haven't already
    if url not in _FEED_URLS:
        feed_url = _channel_to_feed(url)
        if not feed_url:
            return None

        _FEED_URLS[url] = feed_url

    # download the feed
    feed = _download_feed(_FEED_URLS[url])
    if not feed:
        return None

    channel_title = pathvalidate.sanitize_filename(feed.feed.title)

    # make sure the output directory exists
    if not _create_channel_directory(config, channel_title):
        return None

    # download the individual videos
    for entry in feed.entries:
        _download_entry(config, channel, feed, entry)

    return channel_title


def _clean_channel(config, channel, channel_title):
    """
    Clean up the output directory for an individual channel.

    :param dict config: Config dict.
    :param dict channel: Individual channel config.
    :param str channel_title: Path-sanitized channel title.
    """
    if _DEBUG:
        print('Cleaning up channel:', channel_title)

    now = datetime.date.today()
    delta = datetime.timedelta(days=channel['keep_days'])

    for name in os.listdir(os.path.join(config['output_directory'],
                                        channel_title)):
        # we only keep files that match the expected format and are within the
        # configured date range
        regex = r'\d{4}-\d{2}-\d{2} - .* \[[\w_-]+\]\.(mp4|nfo)'
        if re.fullmatch(regex, name):
            date = datetime.date.fromisoformat(name[0:10])
            if now - date < delta:
                continue

        full = os.path.join(config['output_directory'], channel_title, name)

        if _DEBUG:
            print('Removing:', full)

        try:
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.unlink(full)
        except OSError as e:
            print('Failed to remove {}: {}'.format(full, e))


def _clean_output_directory(config, current_channel_titles):
    """
    Clean up the output directory.

    :param dict config: Config dict.
    :param str[] current_channel_titles: List of path-sanitized channel titles.
    """
    if _DEBUG:
        print('Cleaning up output directory')

    for name in os.listdir(config['output_directory']):
        if name in current_channel_titles:
            continue

        full = os.path.join(config['output_directory'], name)

        if _DEBUG:
            print('Removing:', full)

        try:
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.unlink(full)
        except OSError as e:
            print('Failed to remove {}: {}'.format(full, e))


def _download_channels(config):
    """
    Download the videos for all configured channels.

    :param dict config: Config dict.
    """
    if _DEBUG:
        print('Downloading all channels')

    channel_titles = []

    for channel in config['channels']:
        # first, download the latest things
        channel_title = _download_channel(config, channel)
        if not channel_title:
            continue

        channel_titles.append(channel_title)

        # then, clean up old videos
        _clean_channel(config, channel, channel_title)

    # now, clean up any files and directories that don't belong
    _clean_output_directory(config, channel_titles)


def _trigger_jellyfin_scan(config):
    """
    Trigger a library update on Jellyfin.

    :param dict config: Config dict.
    """
    if _DEBUG:
        print('Triggering Jellyfin update')

    base_url = 'http'

    if config['jellyfin']['tls']:
        base_url += 's'

    base_url += '://{}:{}{}'.format(
        config['jellyfin']['host'],
        config['jellyfin']['port'],
        config['jellyfin']['path'].rstrip('/'),
    )

    try:
        if _DEBUG:
            print('Fetching Jellyfin libraries')

        url = '{}/Library/VirtualFolders'.format(base_url)
        response = requests.get(
            url,
            params={'api_key': config['jellyfin']['api_key']}
        )
    except requests.exceptions.RequestException as e:
        print('Failed to look up Jellyfin libraries:', e)
        return

    libraries = response.json()
    item_id = None
    for library in libraries:
        if library['Name'] == config['jellyfin']['library_name']:
            item_id = library['ItemId']
            break

    if not item_id:
        print('Jellyfin library not found')
        return

    if _DEBUG:
        print('Found Jellyfin library ID:', item_id)

    try:
        url = '{}/Items/{}/Refresh'.format(base_url, item_id)
        requests.post(
            url,
            params={
                'api_key': config['jellyfin']['api_key'],
                'Recursive': 'true',
                'ImageRefreshMode': 'Default',
                'MetadataRefreshMode': 'Default',
                'ReplaceAllImages': 'false',
                'ReplaceAllMetadata': 'false',
            }
        )
    except requests.exceptions.RequestException as e:
        print('Failed to trigger Jellyfin scan:', e)


def main():
    """
    Run the program.

    This parses arguments, then enters an infinite loop, constantly fetching
    channel feeds and downloding new videos.
    """
    parser = argparse.ArgumentParser(
        description='Monitor YouTube channels for new videos and import into Jellyfin.'  # noqa
    )
    parser.add_argument(
        '--config',
        dest='config',
        type=str,
        help='path to config file',
        required=True,
    )
    parser.add_argument(
        '--debug',
        dest='debug',
        action='store_true',
        default=False,
        help='enable debugging mode',
    )
    args = parser.parse_args()

    if args.debug:
        global _DEBUG
        _DEBUG = True

    try:
        while True:
            # read the config on each iteration to pick up new feeds and such
            config = _read_config(args.config)

            # download specified channels
            _download_channels(config)

            if 'jellyfin' in config:
                _trigger_jellyfin_scan(config)

            # sleep for the specified interval
            if _DEBUG:
                print('Sleeping for {} seconds'.format(config['interval']))

            time.sleep(config['interval'])
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
