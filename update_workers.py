from PyQt5.QtCore import QThread, pyqtSignal

from update_service import UpdateManifest, download_update, fetch_update_manifest


class UpdateCheckWorker(QThread):
    update_found = pyqtSignal(object)
    no_update = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version

    def run(self) -> None:
        from update_service import is_newer_version

        try:
            manifest = fetch_update_manifest()
            if is_newer_version(manifest.version, self.current_version):
                self.update_found.emit(manifest)
            else:
                self.no_update.emit()
        except Exception as error:
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
