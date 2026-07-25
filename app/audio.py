import re
from pathlib import Path

_AUDIO_DIR = Path(__file__).parent.parent / 'audio'
_EXTS = ('.mp3', '.ogg', '.wav')

# Per-playlist music volume: the career soundtrack is a separately mastered
# (typically quieter) placeholder track, so it gets its own, louder level
# rather than sharing the main playlist's — tune per-set here instead of
# re-encoding/normalizing every career track as they're added.
_MUSIC_VOLUME_MAIN   = 0.55
_MUSIC_VOLUME_CAREER = 0.85

try:
    from PyQt6.QtMultimedia import (QMediaPlayer, QAudioOutput, QMediaMetaData,
                                    QSoundEffect)
    from PyQt6.QtCore import QObject, QUrl, pyqtSignal
    _OK = True
except ImportError:
    _OK = False


def _parse_track(path: Path) -> tuple[str, str]:
    """Fallback: (title, artist) from filename. 'Title - Artist.mp3' or 'Title.mp3'."""
    stem = re.sub(r'^\d+[\.\-_\s]+', '', path.stem).strip()
    if ' - ' in stem:
        title, artist = stem.split(' - ', 1)
    else:
        title, artist = stem, ''
    title = re.sub(r'\s*\([^)]*\)', '', title).strip()
    return title, artist.strip()


if _OK:
    class AudioManager(QObject):
        """
        Playlist loop + one-shot SFX.

        Drop audio files into audio/music/ — plays in filename order, loops.
        SFX files: audio/sfx/navigate · select · back  (.wav/.mp3/.ogg)
        Press M to mute/unmute the music playlist — navigation SFX always play.
        """

        track_changed = pyqtSignal(str, str)  # title, artist

        def __init__(self):
            super().__init__()
            self._muted = False
            # Two playlists: the main one (audio/music/*) and a career-only one
            # (audio/music/career/*). `_playlist`/`_track_info` always point at
            # whichever is currently active — see play_career_music/play_main_music.
            self._main_playlist: list[Path] = []
            self._main_track_info: list[tuple[str, str]] = []
            self._career_playlist: list[Path] = []
            self._career_track_info: list[tuple[str, str]] = []
            self._active_set = 'main'
            self._playlist: list[Path] = []
            self._track_info: list[tuple[str, str]] = []
            self._idx = 0
            # Set right before _activate_set's automatic main->career switch
            # starts a track, so that switch doesn't pop the now-playing toast
            # (play_at() — the user explicitly picking a track on the
            # Soundtrack page — never sets this, so that toast still shows).
            # The career set itself is always toast-free regardless of this
            # flag (see _active_set checks below) — it's a single placeholder
            # theme track, so looping back to it has nothing new to announce.
            self._suppress_toast = False
            self._current_path: Path | None = None
            self._meta_emitted = False
            self._started = False

            self._music_player = QMediaPlayer()
            self._music_out = QAudioOutput()
            self._music_player.setAudioOutput(self._music_out)
            self._music_out.setVolume(_MUSIC_VOLUME_MAIN)
            self._music_player.mediaStatusChanged.connect(self._on_status)
            self._music_player.metaDataChanged.connect(self._on_metadata)
            self._music_player.playbackStateChanged.connect(self._on_playback_state)

            # SFX are preloaded once (see _load_sfx). Reusing a single
            # QMediaPlayer with setSource() on every key press rebuilt the whole
            # decode pipeline each time, which made every navigation hitch.
            self._sfx: dict[str, 'QSoundEffect'] = {}
            self._sfx_players: dict[str, 'QMediaPlayer'] = {}
            self._sfx_outs: list = []

            self._load_playlist()
            self._load_sfx()

        def _load_playlist(self) -> None:
            def collect(d: Path) -> list[Path]:
                files: list[Path] = []
                for ext in _EXTS:
                    files.extend(d.glob(f'*{ext}'))   # non-recursive: skips career/
                return sorted(files, key=lambda p: p.name.lower())

            music_dir = _AUDIO_DIR / 'music'
            self._main_playlist   = collect(music_dir)
            self._career_playlist = collect(music_dir / 'career')
            self._main_track_info   = [_parse_track(p) for p in self._main_playlist]
            self._career_track_info = [_parse_track(p) for p in self._career_playlist]
            # Main is active until play_career_music() switches it.
            self._playlist   = self._main_playlist
            self._track_info = self._main_track_info

        def _load_sfx(self) -> None:
            """Preload each SFX once. WAV files use QSoundEffect (low-latency,
            no per-play decode); anything else keeps its own preloaded player."""
            sfx_dir = _AUDIO_DIR / 'sfx'
            if not sfx_dir.exists():
                return
            seen: set[str] = set()
            for ext in _EXTS:
                for p in sorted(sfx_dir.glob(f'*{ext}')):
                    if p.stem in seen:
                        continue
                    seen.add(p.stem)
                    if ext == '.wav':
                        eff = QSoundEffect(self)
                        eff.setSource(QUrl.fromLocalFile(str(p)))
                        eff.setVolume(0.8)
                        self._sfx[p.stem] = eff
                    else:
                        pl = QMediaPlayer()
                        out = QAudioOutput()
                        pl.setAudioOutput(out)
                        out.setVolume(0.8)
                        pl.setSource(QUrl.fromLocalFile(str(p)))
                        self._sfx_players[p.stem] = pl
                        self._sfx_outs.append(out)

        def start(self) -> None:
            if self._playlist and not self._started:
                self._started = True
                self._play_track(0)

        def _play_track(self, idx: int) -> None:
            self._idx = idx % len(self._playlist)
            self._current_path = self._playlist[self._idx]
            self._meta_emitted = False
            self._music_player.setSource(QUrl.fromLocalFile(str(self._current_path)))
            self._music_player.play()

        def _on_metadata(self) -> None:
            if self._meta_emitted:
                return
            meta = self._music_player.metaData()
            title = meta.value(QMediaMetaData.Key.Title)
            if not title:
                return
            raw = (meta.value(QMediaMetaData.Key.Author) or
                   meta.value(QMediaMetaData.Key.AlbumArtist))
            if raw:
                artist = ', '.join(str(v) for v in raw) if isinstance(raw, list) else str(raw)
            else:
                # metadata has no artist tag — keep filename-parsed artist
                artist = self._track_info[self._idx][1]
            self._meta_emitted = True
            clean_title = re.sub(r'\s*\([^)]*\)', '', str(title)).strip()
            info = (clean_title, artist)
            self._track_info[self._idx] = info
            suppress = self._suppress_toast or self._active_set == 'career'
            self._suppress_toast = False
            if suppress:
                return
            self.track_changed.emit(*info)

        def _on_playback_state(self, state) -> None:
            if state == QMediaPlayer.PlaybackState.PlayingState and not self._meta_emitted:
                self._meta_emitted = True
                suppress = self._suppress_toast or self._active_set == 'career'
                self._suppress_toast = False
                if self._current_path and not suppress:
                    info = _parse_track(self._current_path)
                    self.track_changed.emit(*info)

        def _on_status(self, status) -> None:
            if status == QMediaPlayer.MediaStatus.EndOfMedia and self._playlist:
                self._play_track(self._idx + 1)

        def play_at(self, idx: int) -> None:
            if 0 <= idx < len(self._playlist):
                self._play_track(idx)

        def play_career_music(self) -> None:
            """Switch to the career-only soundtrack (audio/music/career/). No-op
            if that folder has no tracks yet — the main playlist keeps playing
            until the user drops files in (see _activate_set)."""
            self._activate_set('career')

        def play_main_music(self) -> None:
            """Switch back to the main soundtrack (e.g. on returning home)."""
            self._activate_set('main')

        def _activate_set(self, which: str) -> None:
            if which == self._active_set:
                return
            playlist = self._career_playlist if which == 'career' else self._main_playlist
            if not playlist:
                return   # nothing to switch to (career folder still empty)
            self._active_set = which
            self._playlist   = playlist
            self._track_info = (self._career_track_info if which == 'career'
                                else self._main_track_info)
            self._music_out.setVolume(
                _MUSIC_VOLUME_CAREER if which == 'career' else _MUSIC_VOLUME_MAIN)
            if self._started:
                self._suppress_toast = True   # automatic switch — no now-playing popup
                self._play_track(0)   # restart from the new set's first track

        def play_sfx(self, key: str) -> None:
            """Navigation SFX play regardless of mute — M only silences the
            music playlist, not UI feedback sounds."""
            eff = self._sfx.get(key)
            if eff is not None:
                eff.play()          # retriggers from the start; no re-decode
                return
            pl = self._sfx_players.get(key)
            if pl is not None:
                pl.setPosition(0)
                pl.play()

        def toggle_mute(self) -> None:
            self._muted = not self._muted
            self._music_out.setMuted(self._muted)
            if not self._muted:
                self._music_player.play()

        def pause_music(self) -> None:
            """Silence the background playlist (e.g. while a page plays its
            own audio) without touching the user's mute/SFX state."""
            self._music_player.pause()

        def resume_music(self) -> None:
            if self._started and not self._muted:
                self._music_player.play()

        @property
        def playlist_info(self) -> list[tuple[str, str]]:
            return list(self._track_info)

        @property
        def current_idx(self) -> int:
            return self._idx

        @property
        def muted(self) -> bool:
            return self._muted

else:
    class AudioManager:  # type: ignore[no-redef]
        """Stub when PyQt6.QtMultimedia is unavailable."""
        def __init__(self): pass
        def start(self) -> None: pass
        def play_at(self, idx: int) -> None: pass
        def play_career_music(self) -> None: pass
        def play_main_music(self) -> None: pass
        def play_sfx(self, key: str) -> None: pass
        def toggle_mute(self) -> None: pass
        def pause_music(self) -> None: pass
        def resume_music(self) -> None: pass
        @property
        def playlist_info(self) -> list: return []
        @property
        def current_idx(self) -> int: return 0
        @property
        def muted(self) -> bool: return False
