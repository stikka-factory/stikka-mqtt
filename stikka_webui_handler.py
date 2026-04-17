"""
stikka_webui_handler.py
=======================
Homepage interaction handlers for Stikka-NG.

All UI event callbacks live in :class:`HomepageHandlers`.  An instance is
constructed at the top of the homepage route function, UI widget references
are injected after widget creation, and the methods are passed directly as
NiceGUI ``on_click`` / ``on_change`` callbacks.

This separation keeps the voluminous widget-layout code in
:mod:`stikka_webui` clean and the business logic here testable.
"""

from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Callable

from nicegui import ui
from PIL import Image

import stikka_label_helper as lh
import stikka_print_it as pi

log = lh.log


class HomepageHandlers:
    """Owns all user-interaction callbacks for the main homepage.

    Attributes:
        state: Mutable UI state dict shared with the widget layout.
        config: Live application configuration dict.
        fonts_by_name: Mapping of font display-name → absolute font path.
        record_print: Callable that increments the print-statistics CSV.
        webcam_video_id: HTML ``id`` of the ``<video>`` element.
        webcam_canvas_id: HTML ``id`` of the hidden ``<canvas>`` element.

    The following attributes must be set **after** widget creation before any
    handler is invoked:

    - ``preview`` – the :class:`nicegui.ui.interactive_image` element.
    - ``countdown_label`` – the countdown :class:`nicegui.ui.label`.
    - ``capture_button`` – the Capture :class:`nicegui.ui.button`.
    - ``raw_zpl_area`` – the raw-ZPL :class:`nicegui.ui.textarea`.
    - ``zpl_preview`` – the ZPL preview :class:`nicegui.ui.image`.
    - ``webcam_dialog`` – the :class:`nicegui.ui.dialog` component.
    """

    def __init__(
        self,
        state: dict,
        config: dict,
        fonts_by_name: dict[str, str],
        record_print: Callable[[str], None],
        webcam_video_id: str,
        webcam_canvas_id: str,
    ) -> None:
        """Initialise the handler with shared state and configuration.

        Args:
            state: Mutable UI state dict.
            config: Application configuration dict.
            fonts_by_name: Mapping of font name → font file path.
            record_print: Function to call after a successful print to update
                the statistics CSV.
            webcam_video_id: HTML ``id`` attribute for the ``<video>`` element.
            webcam_canvas_id: HTML ``id`` attribute for the hidden
                ``<canvas>`` element used for frame capture.
        """
        self.state = state
        self.config = config
        self.fonts_by_name = fonts_by_name
        self.record_print = record_print
        self.webcam_video_id = webcam_video_id
        self.webcam_canvas_id = webcam_canvas_id

        # Populated after widget construction
        self.preview = None
        self.countdown_label = None
        self.capture_button = None
        self.raw_zpl_area = None
        self.zpl_preview = None
        self.webcam_dialog = None

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def refresh_preview(self) -> None:
        """Re-render the label preview and update the preview widget.

        Calls :func:`stikka_label_helper.render_preview` with the current
        state and updates the ``src`` of the interactive-image widget.
        """
        rendered = lh.render_preview(
            state=self.state,
            fonts_by_name=self.fonts_by_name,
            config=self.config,
        )
        self.preview.set_source(lh.pil_to_data_url(rendered))

    def update_state(self, **kwargs) -> None:
        """Merge *kwargs* into the UI state dict and refresh the preview.

        Args:
            **kwargs: Key-value pairs to update in ``self.state``.
        """
        self.state.update(kwargs)
        self.refresh_preview()

    # ------------------------------------------------------------------
    # Image source handlers
    # ------------------------------------------------------------------

    def get_cat_handler(self) -> None:
        """Fetch a random cat image and load it as the active label image."""
        log.debug('[magenta]Get Cat[/magenta] clicked')
        cat_image = lh.get_cat().convert('RGB')
        self.state['original_image'] = cat_image.copy()
        self.state['image'] = cat_image
        self.state['rotate_image_angle'] = 0
        self.state['image_source_kind'] = 'cat'
        self.refresh_preview()

    def get_dog_handler(self) -> None:
        """Fetch a random dog image and load it as the active label image."""
        log.debug('[magenta]Get Dog[/magenta] clicked')
        dog_image = lh.get_dog().convert('RGB')
        self.state['original_image'] = dog_image.copy()
        self.state['image'] = dog_image
        self.state['rotate_image_angle'] = 0
        self.state['image_source_kind'] = 'dog'
        self.refresh_preview()

    def clear_handler(self) -> None:
        """Clear the active image and reset the label to blank."""
        log.debug('[magenta]Clear[/magenta] clicked')
        self.state['image'] = None
        self.state['original_image'] = None
        self.state['rotate_image_angle'] = 0
        self.state['image_source_kind'] = 'none'
        self.refresh_preview()

    def rotate_image_handler(self, angle: int) -> None:
        """Rotate the original image to an absolute *angle* and refresh.

        Args:
            angle: Absolute rotation angle in degrees (0, 90, 180, 270).
        """
        if self.state['original_image'] is None:
            return
        log.debug(f'[magenta]Rotate Image[/magenta] → {angle}°')
        self.state['rotate_image_angle'] = angle
        self.state['image'] = lh.rotate_image(self.state['original_image'], angle)
        self.refresh_preview()

    async def upload_handler(self, e) -> None:
        """Handle a file-upload event from a NiceGUI upload widget.

        Decodes the uploaded file (image or PDF), stores it in *state*, and
        refreshes the preview.

        Args:
            e: NiceGUI ``UploadEventArguments`` object.
        """
        log.debug('[magenta]Upload[/magenta] clicked')
        try:
            uploaded = await lh.uploaded_file_to_image(e)
            self.state['original_image'] = uploaded.copy()
            self.state['image'] = uploaded
            self.state['rotate_image_angle'] = 0
            self.state['image_source_kind'] = 'upload'
            self.refresh_preview()
        except Exception as exc:
            log.error(f'Could not process uploaded file: {exc}')
            ui.notify('Upload failed. Please provide an image or a valid PDF file.', type='negative')

    # ------------------------------------------------------------------
    # Webcam
    # ------------------------------------------------------------------

    async def stop_webcam_stream(self) -> None:
        """Stop all active webcam media tracks via JavaScript."""
        await ui.run_javascript(f'''
            (() => {{
                const video = document.getElementById('{self.webcam_video_id}');
                if (!video || !video.srcObject) return false;
                const stream = video.srcObject;
                stream.getTracks().forEach(track => track.stop());
                video.srcObject = null;
                return true;
            }})()
        ''')

    async def open_webcam_dialog(self) -> None:
        """Open the webcam capture dialog and start the camera stream.

        If the browser does not support ``getUserMedia`` or the user denies
        permission, the dialog is closed and a notification is shown.
        """
        self.webcam_dialog.open()
        result = await ui.run_javascript(f'''
            (async () => {{
                const video = document.getElementById('{self.webcam_video_id}');
                if (!video) return 'missing-video';
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return 'unsupported';
                try {{
                    const stream = await navigator.mediaDevices.getUserMedia({{ video: true }});
                    video.srcObject = stream;
                    await video.play();
                    return 'ok';
                }} catch (error) {{
                    const reason = error?.message || error?.name || 'unknown';
                    return `error:${{reason}}`;
                }}
            }})()
        ''')
        if result == 'ok':
            log.info('Webcam stream started successfully.')
            return

        await self.stop_webcam_stream()
        self.webcam_dialog.close()
        if result == 'unsupported':
            ui.notify('Browser webcam API is not supported on this device.', type='negative')
        else:
            ui.notify('Could not access webcam. Please allow camera permission.', type='negative')

    async def close_webcam_dialog(self) -> None:
        """Stop the webcam stream and close the capture dialog."""
        await self.stop_webcam_stream()
        self.webcam_dialog.close()

    async def capture_webcam_image(self) -> None:
        """Show a 3-second countdown, capture a webcam frame, and load it.

        The captured frame is stored in *state* as the active label image.
        """
        import asyncio

        self.capture_button.enabled = False
        self.countdown_label.visible = True

        for seconds in [3, 2, 1]:
            self.countdown_label.set_text(str(seconds))
            await asyncio.sleep(1)

        self.countdown_label.visible = False

        data_url = await ui.run_javascript(f'''
            (() => {{
                const video = document.getElementById('{self.webcam_video_id}');
                const canvas = document.getElementById('{self.webcam_canvas_id}');
                if (!video || !canvas) return '';
                if (!video.videoWidth || !video.videoHeight) return '';
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                return canvas.toDataURL('image/png');
            }})()
        ''')

        if not data_url:
            ui.notify('No webcam frame available yet. Try again in a moment.', type='warning')
            self.capture_button.enabled = True
            return

        payload = data_url.split(',', 1)[1] if ',' in data_url else data_url
        with Image.open(BytesIO(base64.b64decode(payload))) as captured:
            captured_rgb = captured.convert('RGB')

        self.state['original_image'] = captured_rgb.copy()
        self.state['image'] = captured_rgb
        self.state['rotate_image_angle'] = 0
        self.state['image_source_kind'] = 'webcam'
        await self.close_webcam_dialog()
        self.refresh_preview()
        log.info('Webcam image captured and loaded successfully.')
        self.capture_button.enabled = True

    # ------------------------------------------------------------------
    # ZPL raw editor
    # ------------------------------------------------------------------

    def preview_zpl_handler(self, _e) -> None:
        """Render a preview of the raw ZPL command via the Labelary API.

        Updates the ZPL preview image widget.

        Args:
            _e: Unused NiceGUI event argument.
        """
        log.debug('[magenta]Preview ZPL[/magenta] clicked')
        printer = self.config['printers'][self.state['selected_printer']]
        dpi = printer.get('dpi', 300)
        label_width_mm = printer['label'].get('width', 80)
        label_length_mm = printer['label'].get('length', 0)
        zpl_data = self.raw_zpl_area.value or ''
        zpl_img = pi.get_zpl_preview(zpl_data, dpi=dpi, width=label_width_mm, height=label_length_mm)
        if zpl_img is not None:
            self.zpl_preview.set_source(lh.pil_to_data_url(zpl_img))
        log.debug('ZPL preview updated')

    def raw_zpl_handler(self, _e) -> None:
        """Send the raw ZPL command from the text area directly to the printer.

        Args:
            _e: Unused NiceGUI event argument.
        """
        log.debug('[magenta]Send Raw ZPL[/magenta] clicked')
        printer = self.config['printers'][self.state['selected_printer']]
        if printer['type'] != 'zpl':
            log.error('Selected printer does not support ZPL commands.')
            ui.notify('Selected printer does not support raw ZPL commands.', type='negative')
            return

        zpl_data = self.state.get('raw_zpl', '')
        if not zpl_data.strip():
            ui.notify('Please enter a valid ZPL command before sending.', type='warning')
            return

        host, port = printer.get('connection', '').split(':')
        pi.print_zpl(zpl_data, host=host, port=int(port))
        ui.notify('Raw ZPL command sent to printer.', type='positive')

    # ------------------------------------------------------------------
    # Print handler
    # ------------------------------------------------------------------

    def stikka_handler(self, _e, download: bool = False) -> None:
        """Render the current label and send it to the selected printer.

        For ``download=True`` the rendered image is offered as a browser
        download instead of being sent to a physical printer.

        Dispatch table:
        - ``"file"``      → download PNG
        - ``"zpl"``       → send ZPL over TCP (or download ``.zpl``)
        - ``"brother_ql"`` → send raster job via brother_ql
        - ``"seiko_slp"`` → send raster job via pyusb

        Args:
            _e: Unused NiceGUI event argument.
            download: If ``True``, serve the output as a file download.
        """
        log.info('[magenta]Stikka[/magenta] clicked')
        printer = self.config['printers'][self.state['selected_printer']]
        printer_type = printer['type']
        log.debug(f'Selected printer type: {printer_type}')

        img = lh.render_preview(
            state=self.state,
            fonts_by_name=self.fonts_by_name,
            config=self.config,
        )
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        if printer_type == 'file':
            ui.download.content(
                lh.pil_to_bytes(img, fmt='PNG'),
                filename=f'sticka_{timestamp}.png',
                media_type='image/png',
            )

        elif printer_type == 'zpl':
            dpi = printer.get('dpi', 300)
            label_width_mm = printer['label'].get('width', 80)
            label_length_mm = printer['label'].get('length', 0)
            vertical_offset_mm = printer['label'].get('vertical_offset', 0)
            log.debug(
                f'{printer["name"]} DPI: {dpi}, label: {label_width_mm}x{label_length_mm}mm, '
                f'v-offset: {vertical_offset_mm}mm'
            )
            zpl_data = pi.img_to_zpl(
                img,
                dpi=dpi,
                label_width_mm=label_width_mm,
                label_length_mm=label_length_mm,
                vertical_offset_mm=vertical_offset_mm,
            )
            if download:
                ui.download.content(zpl_data.encode('utf-8'), filename=f'sticka_{timestamp}.zpl')
            else:
                host, port = printer.get('connection', '').split(':')
                try:
                    pi.print_zpl(zpl_data, host=host, port=int(port))
                    self.record_print(self.state['image_source_kind'])
                    ui.notify(f"Print recorded: {self.state['image_source_kind']}", type='positive')
                except Exception as exc:
                    log.error(f'ZPL print error: {exc}')
                    ui.notify(f'Print failed: {exc}', type='negative')

        elif printer_type == 'brother_ql':
            if download:
                ui.download.content(
                    lh.pil_to_bytes(img, fmt='PNG'),
                    filename=f'sticka_{timestamp}.png',
                    media_type='image/png',
                )
            else:
                dpi = printer.get('dpi', 300)
                label_width_mm = printer['label'].get('width', 80)
                label_length_mm = printer['label'].get('length', 0)
                model = printer.get('name', '').split()[-1]
                if not model:
                    log.error(f'Printer model not found in name: {printer["name"]}')
                    ui.notify('Printer model not configured for Brother QL printer.', type='negative')
                    return
                log.debug(f'Printing on Brother QL {model} @ {dpi} DPI')
                try:
                    pi.print_ql(
                        img,
                        identfier=printer['connection'],
                        backend_name=printer.get('backend_name', 'pyusb'),
                        model=model,
                        dpi=dpi,
                        label_width_mm=label_width_mm,
                        label_length_mm=label_length_mm,
                    )
                    self.record_print(self.state['image_source_kind'])
                    ui.notify(f"Print recorded: {self.state['image_source_kind']}", type='positive')
                except Exception as exc:
                    log.error(f'Brother QL print error: {exc}')
                    ui.notify(f'Print failed: {exc}', type='negative')

        elif printer_type == 'seiko_slp':
            if download:
                ui.download.content(
                    lh.pil_to_bytes(img, fmt='PNG'),
                    filename=f'sticka_{timestamp}.png',
                    media_type='image/png',
                )
            else:
                try:
                    pi.print_seiko(img, printer_config=printer)
                    self.record_print(self.state['image_source_kind'])
                    ui.notify(f"Print recorded: {self.state['image_source_kind']}", type='positive')
                except RuntimeError as exc:
                    log.error(f'Seiko print error: {exc}')
                    ui.notify(f'Print failed: {exc}', type='negative')

        else:
            log.error(f'Unsupported printer type: {printer_type}')
            ui.notify('Selected printer has an unsupported type.', type='negative')
