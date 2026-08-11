from PyQt5.QtCore import QThread, pyqtSignal

from update_service import (
    UpdateManifest,
    download_update,
    fetch_update_manifest,
    load_cached_manifest,
    save_cached_manifest,
)


class UpdateCheckWorker(QThread):
    manifest_ready = pyqtSignal(object, bool)
    failed = pyqtSignal(str)

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version

    def run(self) -> None:
        try:
            manifest = fetch_update_manifest()
            save_cached_manifest(manifest)
            self.manifest_ready.emit(manifest, False)
        except Exception as error:
            cached_manifest = load_cached_manifest()
            if cached_manifest is not None:
                self.manifest_ready.emit(cached_manifest, True)
            else:
                self.failed.emit(str(error))


class UpdateDownloadWorker(QThread):
    progress_changed = pyqtSignal(int)
    completed = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, manifest: UpdateManifest):
        super().__init__()
        self.manifest = manifest

    def run(self) -> None:
        try:
            archive_path = download_update(
                self.manifest,
                progress_callback=self.progress_changed.emit,
            )
            self.completed.emit(self.manifest, archive_path)
        except Exception as error:
            self.failed.emit(str(error))
