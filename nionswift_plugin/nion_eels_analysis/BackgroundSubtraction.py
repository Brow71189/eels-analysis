from __future__ import annotations

# imports
import gettext
import numpy
import typing

# local libraries
from nion.data import Core
from nion.data import DataAndMetadata
from nion.eels_analysis import BackgroundModel
from nion.swift.model import DataStructure
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.swift.model import Schema
from nion.swift import Facade
from nion.utils import Registry


_ = gettext.gettext


def normalized_interval(interval: tuple[float, float]) -> tuple[float, float]:
    """Ensure the interval is normalized, i.e., the first value is less than the second.

    This can happen during dragging of the interval graphics, where the user might drag the left handle to the right
    of the right handle. Until this is handled cleanly in the UI, ensure the interval is normalized here.
    """
    return min(interval), max(interval)


class EELSFitBackground:
    label = _("EELS Fit Background")
    inputs = {
        "eels_spectrum_data_item": {"label": _("EELS Spectrum")},
        "background_model": {"label": _("Background Model"), "entity_id": "background_model"},
        "fit_interval_graphics": {"label": _("Fit")},
        }
    outputs = {
        "background": {"label": _("Background")},
        "subtracted": {"label": _("Subtracted")},
    }

    def __init__(self, computation: Facade.Computation, **kwargs: typing.Any) -> None:
        self.computation = computation
        self.__background_xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__subtracted_xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None

    def execute(self, eels_spectrum_data_item: Facade.DataItem, background_model: Facade.DataStructure, fit_interval_graphics: typing.Sequence[Facade.Graphic], **kwargs: typing.Any) -> None:
        spectrum_xdata = eels_spectrum_data_item.xdata
        assert spectrum_xdata
        assert spectrum_xdata.is_datum_1d
        assert spectrum_xdata.datum_dimensional_calibrations[0].units == "eV"
        eels_spectrum_xdata = spectrum_xdata
        # fit_interval_graphics.interval returns normalized coordinates. create calibrated intervals.
        fit_intervals: typing.List[BackgroundModel.BackgroundInterval] = list()
        for fit_interval_graphic in fit_interval_graphics:
            fit_intervals.append(normalized_interval(fit_interval_graphic.interval))
        fit_minimum = min([fit_interval[0] for fit_interval in fit_intervals])
        signal_interval = fit_minimum, 1.0
        signal_xdata = BackgroundModel.get_calibrated_interval_slice(eels_spectrum_xdata, signal_interval)
        background_xdata = None
        subtracted_xdata = None
        background_model_id = background_model.structure_type
        for component in Registry.get_components_by_type("background-model"):
            if background_model_id == component.background_model_id:
                fit_result = component.fit_background(spectrum_xdata=spectrum_xdata, fit_intervals=fit_intervals, background_interval=signal_interval)
                background_xdata = fit_result["background_model"]
                # use 'or' to avoid doing subtraction if subtracted_spectrum already present
                subtracted_xdata = fit_result.get("subtracted_spectrum", None) or Core.calibrated_subtract_spectrum(spectrum_xdata, background_xdata)
        if background_xdata is None:
            background_xdata = DataAndMetadata.new_data_and_metadata(numpy.zeros_like(signal_xdata.data), intensity_calibration=signal_xdata.intensity_calibration, dimensional_calibrations=signal_xdata.dimensional_calibrations)
        if subtracted_xdata is None:
            subtracted_xdata = DataAndMetadata.new_data_and_metadata(signal_xdata.data, intensity_calibration=signal_xdata.intensity_calibration, dimensional_calibrations=signal_xdata.dimensional_calibrations)
        self.__background_xdata = background_xdata
        self.__subtracted_xdata = subtracted_xdata

    def commit(self) -> None:
        assert self.__background_xdata
        assert self.__subtracted_xdata
        self.computation.set_referenced_xdata("background", self.__background_xdata)
        self.computation.set_referenced_xdata("subtracted", self.__subtracted_xdata)


class EELSSubtractBackground:
    label = _("EELS Subtract Background")
    inputs = {
        "spectrum_image_data_item": {"label": _("EELS Image")},
        "background_model": {"label": _("Background Model"), "entity_id": "background_model"},
        "fit_interval_graphics": {"label": _("Fit")},
        }
    outputs = {
        "subtracted": {"label": _("EELS Background Subtracted")},
    }

    def __init__(self, computation: Facade.Computation, **kwargs: typing.Any) -> None:
        self.computation = computation

    def execute(self, spectrum_image_data_item: Facade.DataItem, background_model: Facade.DataStructure, fit_interval_graphics: typing.Sequence[Facade.Graphic], **kwargs: typing.Any) -> None:
        assert spectrum_image_data_item.xdata
        assert spectrum_image_data_item.xdata.is_datum_1d
        assert spectrum_image_data_item.xdata.is_navigable
        assert spectrum_image_data_item.xdata.datum_dimensional_calibrations[0].units == "eV"
        spectrum_image_xdata = spectrum_image_data_item.xdata
        # fit_interval_graphics.interval returns normalized coordinates. create calibrated intervals.
        fit_intervals: typing.List[BackgroundModel.BackgroundInterval] = list()
        for fit_interval_graphic in fit_interval_graphics:
            fit_intervals.append(normalized_interval(fit_interval_graphic.interval))
        subtracted_xdata = None
        background_model_id = background_model.structure_type
        for component in Registry.get_components_by_type("background-model"):
            if background_model_id == component.background_model_id:
                integrate_result = component.subtract_background(spectrum_xdata=spectrum_image_xdata, fit_intervals=fit_intervals)
                subtracted_xdata = integrate_result["subtracted"]
        if subtracted_xdata is None:
            subtracted_xdata = DataAndMetadata.new_data_and_metadata(numpy.zeros(spectrum_image_xdata.navigation_dimension_shape), dimensional_calibrations=spectrum_image_xdata.navigation_dimensional_calibrations)
        self.__subtracted_xdata = subtracted_xdata

    def commit(self) -> None:
        self.computation.set_referenced_xdata("subtracted", self.__subtracted_xdata)


class EELSMapBackgroundSubtractedSignal:
    label = _("EELS Map Background Subtracted Signal")
    inputs = {
        "spectrum_image_data_item": {"label": _("EELS Image")},
        "eels_spectrum_data_item": {"label": _("EELS Spectrum")},
        "background_model": {"label": _("Background Model"), "entity_id": "background_model"},
        "fit_interval_graphics": {"label": _("Fit")},
        "signal_interval_graphic": {"label": _("Signal")},
        }
    outputs = {
        "map": {"label": _("EELS Signal")},
    }

    def __init__(self, computation: Facade.Computation, **kwargs: typing.Any) -> None:
        self.computation = computation

    def execute(self, **kwargs: typing.Any) -> None:
        spectrum_image_data_item = typing.cast(Facade.DataItem, kwargs["spectrum_image_data_item"])
        background_model = typing.cast(Facade.DataStructure, kwargs["background_model"])
        fit_interval_graphics = typing.cast(typing.Sequence[Facade.Graphic], kwargs["fit_interval_graphics"])
        signal_interval_graphic = typing.cast(Facade.Graphic, kwargs["signal_interval_graphic"])
        eels_spectrum_data_item = typing.cast(typing.Optional[Facade.DataItem], kwargs.get("eels_spectrum_data_item"))
        assert spectrum_image_data_item.xdata
        assert spectrum_image_data_item.xdata.is_datum_1d
        assert spectrum_image_data_item.xdata.is_navigable
        assert spectrum_image_data_item.xdata.datum_dimensional_calibrations[0].units == "eV"
        spectrum_image_xdata = spectrum_image_data_item.xdata
        eels_spectrum_xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        if eels_spectrum_data_item:
            eels_spectrum_xdata = eels_spectrum_data_item.xdata
            assert eels_spectrum_xdata
            assert eels_spectrum_xdata.is_datum_1d
            assert eels_spectrum_xdata.datum_dimensional_calibrations[0].units == "eV"
        # fit_interval_graphics.interval returns normalized coordinates. create calibrated intervals.
        fit_intervals: typing.List[BackgroundModel.BackgroundInterval] = list()
        for fit_interval_graphic in fit_interval_graphics:
            fit_intervals.append(normalized_interval(fit_interval_graphic.interval))
        signal_interval = normalized_interval(signal_interval_graphic.interval)
        mapped_xdata = None
        background_model_id = background_model.structure_type
        for component in Registry.get_components_by_type("background-model"):
            if background_model_id == component.background_model_id:
                integrate_result = component.integrate_signal(spectrum_xdata=spectrum_image_xdata, eels_spectrum_xdata=eels_spectrum_xdata, fit_intervals=fit_intervals, signal_interval=signal_interval)
                mapped_xdata = integrate_result["integrated"]
        if mapped_xdata is None:
            mapped_xdata = DataAndMetadata.new_data_and_metadata(numpy.zeros(spectrum_image_xdata.navigation_dimension_shape), dimensional_calibrations=spectrum_image_xdata.navigation_dimensional_calibrations)
        self.__mapped_xdata = mapped_xdata

    def commit(self) -> None:
        self.computation.set_referenced_xdata("map", self.__mapped_xdata)


def add_background_subtraction_computation(api: Facade.API_1, library: Facade.Library, display_item: Facade.Display, data_item: Facade.DataItem, intervals: typing.Sequence[Facade.Graphic]) -> None:
    background = api.library.create_data_item()
    signal = api.library.create_data_item()

    background_model = DataStructure.DataStructure(structure_type="power_law_fit_background_model")
    library._document_model.append_data_structure(background_model)
    background_model.source = background._data_item

    api.library.create_computation("eels.background_subtraction3",
                                   inputs={
                                       "eels_spectrum_data_item": data_item,
                                       "background_model": api._new_api_object(background_model),
                                       "fit_interval_graphics": intervals,
                                   },
                                   outputs={
                                       "background": background,
                                       "subtracted": signal}
                                   )
    for target_interval in intervals:
        target_interval.graphic_id = "background"
        target_interval.label = _("Background")
    display_item._display_item.append_display_data_channel_for_data_item(background._data_item)
    display_item._display_item.append_display_data_channel_for_data_item(signal._data_item)
    display_item._display_item.move_display_layer_at_index_backward(0)
    display_item._display_item.move_display_layer_at_index_backward(1)
    display_item._display_item._set_display_layer_properties(0, label=_("Background"),
                                                             fill_color="rgba(255, 0, 0, 0.3)")
    display_item._display_item._set_display_layer_properties(1, label=_("Signal"), fill_color="#0F0")
    display_item._display_item._set_display_layer_properties(2, label=_("Data"), fill_color="#1E90FF")
    display_item._display_item.set_display_property("legend_position", "top-right")


def subtract_background_from_signal(api: Facade.API_1, window: Facade.DocumentWindow) -> None:
    target_data_item = window.target_data_item
    target_display_item = window.target_display
    if target_display_item and target_data_item:
        target_intervals = [graphic for graphic in target_display_item.selected_graphics if
                            graphic.graphic_type == "interval-graphic"]
        if target_intervals:
            add_background_subtraction_computation(api, window.library, target_display_item, target_data_item, target_intervals)


def subtract_background(api: Facade.API_1, window: Facade.DocumentWindow) -> None:
    target_display = window.target_display
    if target_display:
        target_display_item_data_items = target_display._display_item.data_items
        for computation in api.library._document_model.computations:
            if computation.processing_id == "eels.background_subtraction3":
                if computation.get_input("eels_spectrum_data_item") in target_display_item_data_items and computation.get_output("subtracted") in target_display_item_data_items:
                    eels_spectrum_data_item = computation.get_input("eels_spectrum_data_item")
                    eels_spectrum_data_item = api._new_api_object(eels_spectrum_data_item)
                    fit_interval_graphics = computation.get_input("fit_interval_graphics")
                    fit_interval_graphics = [api._new_api_object(g) for g in fit_interval_graphics]
                    background_model = computation.get_input("background_model")
                    background_model = api._new_api_object(background_model)
                    source_data_items = api.library._document_model.get_source_data_items(eels_spectrum_data_item._data_item)
                    if len(source_data_items) == 1:
                        source_xdata = source_data_items[0].xdata
                        assert source_xdata
                        if source_xdata.is_navigable and source_data_items[0].datum_dimension_count == 1:
                            spectrum_image = api._new_api_object(source_data_items[0])
                            subtracted = api.library.create_data_item_from_data(numpy.zeros(spectrum_image._data_item.xdata.navigation_dimension_shape))
                            api.library.create_computation(
                                "eels.subtract_background",
                                inputs={
                                    "spectrum_image_data_item": spectrum_image,
                                    "fit_interval_graphics": fit_interval_graphics,
                                    "background_model": background_model,
                                },
                                outputs={
                                    "subtracted": subtracted
                                }
                            )
                            window.display_data_item(subtracted)
                    break


def use_signal_for_map(api: Facade.API_1, window: Facade.DocumentWindow) -> None:
    target_display = window.target_display
    target_graphic = target_display.selected_graphics[0] if target_display and len(target_display.selected_graphics) == 1 else None
    target_interval = target_graphic if target_graphic and target_graphic.graphic_type == "interval-graphic" else None
    if target_display and target_interval:
        target_display_item_data_items = target_display._display_item.data_items
        for computation in api.library._document_model.computations:
            if computation.processing_id == "eels.background_subtraction3":
                if computation.get_input("eels_spectrum_data_item") in target_display_item_data_items and computation.get_output("subtracted") in target_display_item_data_items:
                    eels_spectrum_data_item = computation.get_input("eels_spectrum_data_item")
                    eels_spectrum_data_item = api._new_api_object(eels_spectrum_data_item)
                    fit_interval_graphics = computation.get_input("fit_interval_graphics")
                    fit_interval_graphics = [api._new_api_object(g) for g in fit_interval_graphics]
                    background_model = computation.get_input("background_model")
                    background_model = api._new_api_object(background_model)
                    source_data_items = api.library._document_model.get_source_data_items(eels_spectrum_data_item._data_item)
                    if len(source_data_items) == 1:
                        source_xdata = source_data_items[0].xdata
                        assert source_xdata
                        if source_xdata.is_navigable and source_data_items[0].datum_dimension_count == 1:
                            spectrum_image = api._new_api_object(source_data_items[0])
                            map = api.library.create_data_item_from_data(numpy.zeros(spectrum_image._data_item.xdata.navigation_dimension_shape))
                            signal_interval_graphic = target_interval
                            api.library.create_computation(
                                "eels.mapping3",
                                inputs={
                                    "spectrum_image_data_item": spectrum_image,
                                    "eels_spectrum_data_item": eels_spectrum_data_item,
                                    "fit_interval_graphics": fit_interval_graphics,
                                    "signal_interval_graphic": signal_interval_graphic,
                                    "background_model": background_model,
                                },
                                outputs={
                                    "map": map
                                }
                            )
                            window.display_data_item(map)
                    break


ComputationCallable = typing.Callable[[Symbolic._APIComputation], Symbolic.ComputationHandlerLike]
Symbolic.register_computation_type("eels.background_subtraction3", typing.cast(ComputationCallable, EELSFitBackground))
Symbolic.register_computation_type("eels.mapping3", typing.cast(ComputationCallable, EELSMapBackgroundSubtractedSignal))
Symbolic.register_computation_type("eels.subtract_background", typing.cast(ComputationCallable, EELSSubtractBackground))

BackgroundModelEntity = Schema.entity("background_model", None, None, {})


def component_registered(component: Registry._ComponentType, component_types: typing.Set[str]) -> None:
    if "background-model" in component_types:
        # when a background model is registered, create an empty (for now) entity type, and register it with the data
        # structure so that an entity for use with the UI and computations can be created when the data structure loads.
        background_model_entity = Schema.entity(component.background_model_id, BackgroundModelEntity, None, {})
        DataStructure.DataStructure.register_entity(background_model_entity, entity_name=component.title, entity_package_name=component.package_title)


_component_registered_listener = Registry.listen_component_registered_event(component_registered)

# handle any components that have already been registered.
for component in Registry.get_components_by_type("background-model"):
    component_registered(component, {"background-model"})
