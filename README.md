# ytmon

`ytmon` is a script that allows you to "subscribe" to YouTube videos without
having a Google/YouTube account. It works by monitoring the Atom feeds for a
set of channels you'd like to subscribe to and downloading the videos using
[youtube-dl](https://github.com/ytdl-org/youtube-dl). Videos are kept for a
user-configured number of days before being deleted.

## Features

* User-controlled set of subscriptions, each with a configurable number of days
  to keep videos.
* User-configurable options for `youtube-dl`.
* User-configurable scan interval.
* User-configurable file permissions.
* Ability to write out .NFO files compatible with Kodi, Emby, Jellyfin, etc.
* Ability to trigger library updates on Jellyfin.

## Usage

### Docker

```
docker build -t ytmon .
docker run \
    -d \
    --name ytmon \
    --restart unless-stopped \
    -v /opt/docker/ytmon/media:/media \
    -v /opt/docker/ytmon/config:/config \
    ytmon
```

A sample `docker-compose.yml` is also available in this repo.

### Manual

```
# You'll need to install ffmpeg if you don't already have it.
pip3 install -r requirements.txt
./ytmon.py --config /path/to/config.json
```

## Options

* `--config /path/to/config.json` - Path to config file, required.
* `--debug` - Enable additional debug output.

## Configuration

See the sample `config.json` file in this repo.

**NOTE:** `youtube_dl_opts` corresponds to internal options used by
`youtube-dl`, which are not necessarily the same as the usual command-line
switches. You may need to look these up in the `youtube-dl` source.
