#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Catalog facade tests covering mutation callbacks and link management."""

import gc
import logging
import uuid
import weakref
from pathlib import Path

import pytest
from cutecanvas import LinkedGroup
from PySide6.QtGui import QImage, Qt
from qpane.catalog.catalog import Catalog
from qpane.catalog.link import LinkManager
from qpane.types import CatalogEntry


def _make_image(color=Qt.white) -> QImage:
    """Return a tiny solid-colour QImage for catalog tests."""
    image = QImage(8, 8, QImage.Format_ARGB32)
    image.fill(color)
    return image


class FakeCatalog:
    def __init__(self) -> None:
        self.images: dict[uuid.UUID, CatalogEntry] = {}
        self.current_id: uuid.UUID | None = None

    def setImagesByID(self, image_map, current_id):
        self.images = dict(image_map)
        self.current_id = current_id
        return set(), set()

    def addImage(self, image_id, image, path):
        self.images[image_id] = CatalogEntry(image=image, path=path)

    def removeImageByID(self, image_id):
        self.images.pop(image_id, None)
        if self.current_id == image_id:
            self.current_id = next(iter(self.images), None)

    def clearImages(self):
        self.images.clear()
        self.current_id = None

    def containsImage(self, image_id):
        return image_id in self.images

    def getCurrentImage(self):
        entry = self.images.get(self.current_id)
        return entry.image if entry else None

    def getCurrentPath(self):
        entry = self.images.get(self.current_id)
        return entry.path if entry else None

    def getCurrentId(self):
        return self.current_id

    def getAllImages(self):
        return [self.images[iid].image for iid in self.images]

    def getAllPaths(self):
        return [self.images[iid].path for iid in self.images]

    def getImageIds(self):
        return list(self.images.keys())

    def hasImages(self):
        return bool(self.images)

    def setCurrentImageID(self, image_id):
        if image_id in self.images:
            self.current_id = image_id

    def getPath(self, image_id):
        entry = self.images.get(image_id)
        return entry.path if entry else None


class StubCatalogController:
    def __init__(
        self, catalog: FakeCatalog, *, link_manager: LinkManager | None = None
    ) -> None:
        self.catalog = catalog
        self.calls: list[tuple[str, object]] = []
        self.copy_result = True
        self.link_manager = link_manager

    def setImagesByID(self, image_map, current_id, *, display=True):
        self.calls.append(("setImagesByID", display))
        self.catalog.setImagesByID(image_map, current_id)

    def addImage(self, image_id, image, path):
        self.calls.append(("addImage", image_id))
        self.catalog.addImage(image_id, image, path)

    def removeImageByID(self, image_id):
        self.calls.append(("removeImageByID", image_id))
        self.catalog.removeImageByID(image_id)

    def removeImagesByID(self, image_ids):
        deduped = tuple(dict.fromkeys(image_ids))
        removed: list[uuid.UUID] = []
        for image_id in deduped:
            if image_id in self.catalog.images:
                self.catalog.removeImageByID(image_id)
                removed.append(image_id)
        self.calls.append(("removeImagesByID", removed))
        return tuple(removed)

    def clearImages(self):
        self.calls.append(("clearImages", None))
        self.catalog.clearImages()

    def setCurrentImageID(self, image_id):
        self.calls.append(("setCurrentImageID", image_id))
        self.catalog.setCurrentImageID(image_id)

    def saveZoomPanForCurrentImage(self):
        self.calls.append(("saveZoomPanForCurrentImage", None))

    def restoreZoomPanForNewImage(self, image_id):
        self.calls.append(("restoreZoomPanForNewImage", image_id))

    def setLinkedGroups(self, groups):
        self.calls.append(("setLinkedGroups", groups))
        if self.link_manager is not None:
            self.link_manager.setGroups(groups)

    def setAllImagesLinked(self, enabled):
        self.calls.append(("setAllImagesLinked", enabled))
        if self.link_manager is None:
            return
        if enabled and len(self.catalog.images) >= 2:
            group_id = uuid.uuid4()
            self.link_manager.setGroups(
                (
                    LinkedGroup(
                        group_id=group_id,
                        members=tuple(self.catalog.images.keys()),
                    ),
                )
            )
        else:
            self.link_manager.setGroups(())

    def handleDragRequest(self, event):
        self.calls.append(("handleDragRequest", event))

    def copyCurrentImageToClipboard(self):
        self.calls.append(("copyCurrentImageToClipboard", None))
        return self.copy_result

    def displayCurrentCatalogImage(self, *, fit_view=True):
        self.calls.append(("displayCurrentCatalogImage", fit_view))


class StubSwapDelegate:
    def __init__(self) -> None:
        self.navigate_calls: list[tuple[uuid.UUID, bool | None, bool]] = []

    def set_current_image(self, image_id, *, fit_view=None, save_view=True):
        self.navigate_calls.append((image_id, fit_view, save_view))


class RecordingInteraction:
    def __init__(self) -> None:
        self.suspend_calls = 0

    def suspend_overlays_for_navigation(self) -> None:
        self.suspend_calls += 1


class QPaneProbe:
    def __init__(self) -> None:
        self.interaction = RecordingInteraction()


def _build_catalog(*, qpane: QPaneProbe | None = None):
    image_catalog = FakeCatalog()
    link_manager = LinkManager()
    controller = StubCatalogController(image_catalog, link_manager=link_manager)
    swap_delegate = StubSwapDelegate()
    catalog_api = Catalog(
        catalog=image_catalog,
        controller=controller,
        link_manager=link_manager,
        swap_delegate=swap_delegate,
        qpane=qpane,
    )
    return catalog_api, image_catalog, controller, swap_delegate


@pytest.fixture
def catalog_components():
    return _build_catalog()


def test_set_images_by_id_navigates_and_emits_hooks(catalog_components):
    catalog_api, image_catalog, controller, swap_delegate = catalog_components
    mutated: list = []
    navigated: list = []
    catalog_api.setMutationListener(mutated.append)
    catalog_api.onNavigationStarted(navigated.append)
    image_id = uuid.uuid4()
    image_map = {
        image_id: CatalogEntry(image=_make_image(Qt.red), path=Path("first.png"))
    }
    catalog_api.setImagesByID(image_map, image_id)
    assert controller.calls[0] == ("setImagesByID", False)
    assert swap_delegate.navigate_calls == [(image_id, True, False)]
    assert mutated[0].reason == "setImagesByID"
    assert mutated[0].affected_ids == (image_id,)
    assert navigated[0].target_id == image_id
    assert navigated[0].fit_view is True
    assert image_catalog.current_id == image_id


def test_set_current_image_uses_default_fit_setting(catalog_components):
    catalog_api, _, _, swap_delegate = catalog_components
    first_id = uuid.uuid4()
    catalog_api.imageCatalog().setImagesByID(
        {first_id: CatalogEntry(image=_make_image(), path=None)}, first_id
    )
    navigated: list = []
    catalog_api.onNavigationStarted(navigated.append)
    catalog_api.setCurrentImageID(first_id)
    assert swap_delegate.navigate_calls[-1] == (first_id, None, True)
    assert navigated[-1].reason == "setCurrentImageID"


def test_linked_view_group_id_lookup(catalog_components):
    catalog_api, _, _, _ = catalog_components
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    catalog_api.imageCatalog().setImagesByID(
        {
            first_id: CatalogEntry(image=_make_image(Qt.red), path=Path("first.png")),
            second_id: CatalogEntry(
                image=_make_image(Qt.blue), path=Path("second.png")
            ),
        },
        first_id,
    )
    group = LinkedGroup(group_id=uuid.uuid4(), members=(first_id, second_id))
    catalog_api.setLinkedGroups((group,))
    group_id = catalog_api.linkedViewGroupID(first_id)
    assert group_id is not None
    assert catalog_api.linkedViewGroupID(second_id) == group_id
    assert catalog_api.linkedViewGroupID(uuid.uuid4()) is None


def test_metadata_helpers_reflect_catalog_state(catalog_components):
    catalog_api, _, _, _ = catalog_components
    image_id = uuid.uuid4()
    path = Path("foo.png")
    catalog_api.setImagesByID(
        {image_id: CatalogEntry(image=_make_image(Qt.blue), path=path)}, image_id
    )
    assert catalog_api.currentImageID() == image_id
    assert catalog_api.currentImagePath() == path
    assert catalog_api.imagePath(image_id) == path
    assert catalog_api.imagePath(uuid.uuid4()) is None
    assert catalog_api.imageIDs() == [image_id]
    assert catalog_api.imageCount() == 1
    assert catalog_api.hasImages() is True
    assert catalog_api.allImagePaths() == [path]
    assert catalog_api.linkedGroups() == ()


def test_clear_images_reports_previous_ids(catalog_components):
    catalog_api, _, controller, _ = catalog_components
    first = uuid.uuid4()
    second = uuid.uuid4()
    catalog_api.setImagesByID(
        {
            first: CatalogEntry(image=_make_image(Qt.black), path=Path("a.png")),
            second: CatalogEntry(image=_make_image(Qt.white), path=Path("b.png")),
        },
        first,
    )
    mutated: list = []
    catalog_api.setMutationListener(mutated.append)
    catalog_api.clearImages()
    assert controller.calls[-1][0] == "clearImages"
    assert mutated[-1].reason == "clearImages"
    assert set(mutated[-1].affected_ids) == {first, second}


def test_remove_image_by_id_ignores_unknown_ids(catalog_components):
    catalog_api, _, controller, _ = catalog_components
    first = uuid.uuid4()
    catalog_api.setImagesByID(
        {first: CatalogEntry(image=_make_image(), path=None)}, first
    )
    mutated: list = []
    catalog_api.setMutationListener(mutated.append)
    catalog_api.removeImageByID(uuid.uuid4())
    assert controller.calls[-1][0] != "removeImageByID"
    assert mutated == []
    catalog_api.removeImageByID(first)
    assert controller.calls[-1] == ("removeImageByID", first)
    assert mutated[-1].affected_ids == (first,)


def test_remove_images_by_id_batches_mutation(catalog_components):
    catalog_api, image_catalog, controller, _ = catalog_components
    first = uuid.uuid4()
    second = uuid.uuid4()
    third = uuid.uuid4()
    catalog_api.setImagesByID(
        {
            first: CatalogEntry(image=_make_image(Qt.black), path=Path("a.png")),
            second: CatalogEntry(image=_make_image(Qt.white), path=Path("b.png")),
            third: CatalogEntry(image=_make_image(Qt.red), path=Path("c.png")),
        },
        first,
    )
    mutated: list = []
    catalog_api.setMutationListener(mutated.append)
    ghost = uuid.uuid4()
    catalog_api.removeImagesByID([second, first, second, ghost])
    assert controller.calls[-1] == ("removeImagesByID", [second, first])
    assert mutated[-1].reason == "removeImagesByID"
    assert mutated[-1].affected_ids == (second, first)
    assert image_catalog.getImageIds() == [third]


def test_remove_images_by_id_logs_when_no_images_removed(catalog_components, caplog):
    catalog_api, _, controller, _ = catalog_components
    image_id = uuid.uuid4()
    catalog_api.setImagesByID(
        {image_id: CatalogEntry(image=_make_image(), path=None)}, image_id
    )
    mutated: list = []
    catalog_api.setMutationListener(mutated.append)
    caplog.set_level(logging.WARNING)
    controller_calls_before = len(controller.calls)
    missing = uuid.uuid4()
    catalog_api.removeImagesByID([missing])
    assert len(controller.calls) == controller_calls_before + 1
    assert controller.calls[-1] == ("removeImagesByID", [])
    assert "Attempted to remove unknown image_ids" in caplog.text
    assert mutated == []


def test_remove_images_by_id_logs_and_skips_empty_requests(catalog_components, caplog):
    catalog_api, _, controller, _ = catalog_components
    controller_calls_before = len(controller.calls)
    caplog.set_level(logging.INFO)
    catalog_api.removeImagesByID([])
    assert len(controller.calls) == controller_calls_before
    assert "removeImagesByID called with no ids" in caplog.text


def test_copy_current_image_to_clipboard_delegates(catalog_components):
    catalog_api, _, controller, _ = catalog_components
    controller.copy_result = False
    assert catalog_api.copyCurrentImageToClipboard() is False
    assert controller.calls[-1][0] == "copyCurrentImageToClipboard"


def test_navigation_hook_invokes_interaction_suspension():
    qpane_probe = QPaneProbe()
    catalog_api, _, _, swap_delegate = _build_catalog(qpane=qpane_probe)
    catalog_api.onNavigationStarted(
        lambda event: qpane_probe.interaction.suspend_overlays_for_navigation()
    )
    image_id = uuid.uuid4()
    catalog_api.setImagesByID(
        {image_id: CatalogEntry(image=_make_image(), path=None)}, image_id
    )
    catalog_api.setCurrentImageID(image_id)
    assert qpane_probe.interaction.suspend_calls == 2
    first_call = swap_delegate.navigate_calls[0]
    assert first_call[2] is False  # save_view disabled for reset
    assert swap_delegate.navigate_calls[1][2] is True


def test_catalog_releases_qpane_reference_when_collected():
    qpane_probe = QPaneProbe()
    catalog_api, _, _, _ = _build_catalog(qpane=qpane_probe)
    assert catalog_api.qpane() is qpane_probe
    weak_handle = weakref.ref(qpane_probe)
    del qpane_probe
    gc.collect()
    assert weak_handle() is None
    assert catalog_api.qpane() is None
