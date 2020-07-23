#!/usr/bin/env python3

"""Download a single YouTube video/playlist along with a thumbnail and .nfo."""

from lxml import etree
import glob
import os
import re
import subprocess
import sys
import youtube_dl


class YTDLPostProcessor(youtube_dl.postprocessor.common.PostProcessor):
    """Postprocessor to write .nfo files."""

    def run(self, information):
        """
        Run the postprocessor, i.e. write the .nfo file.

        :param dict information: Extracted video information.

        :return: Tuple: list of files to delete, updated information
        """
        _write_nfo(information)

        old_path = information['filepath']

        to_delete = []
        for fname in glob.glob(
                '{}.*'.format(glob.escape(os.path.splitext(old_path)[0]))):
            new_fname = re.sub(r'^(\d{4})(\d{2})(\d{2})', r'\1-\2-\3', fname)
            os.rename(fname, new_fname)

            if new_fname.endswith('.webp'):
                image_old = new_fname
                image_new = re.sub(r'\.webp$', '.png', image_old)

                try:
                    proc = subprocess.run(['convert', image_old, image_new])
                    if proc.returncode == 0:
                        to_delete.append(image_old)
                except (OSError, subprocess.SubprocessError):
                    pass

        new_path = re.sub(r'^(\d{4})(\d{2})(\d{2})', r'\1-\2-\3', old_path)
        information['filepath'] = new_path

        return to_delete, information


def _write_nfo(information):
    """
    Write a Kodi/Emby/Jellyfin-compatible .nfo file for a video.

    :param dict information: Extracted video information.
    """
    movie = etree.Element('movie')
    title = etree.SubElement(movie, 'title')
    title.text = information['fulltitle']
    sorttitle = etree.SubElement(movie, 'sorttitle')
    sorttitle.text = '{}-{}-{} - {}'.format(
        information['upload_date'][0:4],
        information['upload_date'][4:6],
        information['upload_date'][6:8],
        information['fulltitle']
    )
    plot = etree.SubElement(movie, 'plot')
    plot.text = information['description']
    premiered = etree.SubElement(movie, 'premiered')
    premiered.text = '{}-{}-{}'.format(
        information['upload_date'][0:4],
        information['upload_date'][4:6],
        information['upload_date'][6:8]
    )

    try:
        path = re.sub(r'\.mp4$', '.nfo', information['filepath'])
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


def _download_video(url):
    """
    Download a video or playlist.

    :param str url: URL of video or playlist.
    """
    opts = {
        'outtmpl': '%(upload_date)s - %(title)s [%(id)s].%(ext)s',
        'writethumbnail': True,
        'merge_output_format': 'mp4',
        'postprocessor_args': [
            '-strict',
            '-2',
        ],
    }

    try:
        with youtube_dl.YoutubeDL(opts) as ydl:
            ydl.add_post_processor(YTDLPostProcessor())
            ydl.download([url])
    except youtube_dl.utils.YoutubeDLError as e:
        print('Failed to download {}: {}'.format(url, e))
        sys.exit(1)


def main():
    """Run the program."""
    if len(sys.argv) != 2:
        print('Usage:')
        print('\t{} <url>'.format(sys.argv[0]))
        sys.exit(1)

    _download_video(sys.argv[1])


if __name__ == '__main__':
    main()
