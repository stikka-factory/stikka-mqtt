"""Homepage interaction handlers for Stikka-NG."""
from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Callable

import treepoem as _treepoem
from nicegui import ui
from PIL import Image

import stikka_label_helper as lh
import stikka_print_it as pi

log = lh.log


class HomepageHandlers:
    """Owns all user-interaction callbacks for the main homepage."""

    def __init__(
        self,
        state: dict,
        config: dict,
        fonts_by_name: dict[str, str],
        record_print: Callable[[str], None],
        webcam_video_id: str,
        webcam_canvas_id: str,
    ) -> None:
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
        self.camera_select = None

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _get_native_pixels(self) -> tuple[int, int] | None:
        """Return the native dot dimensions for the selected Brother QL label, or None."""
        printer = self.config['printers'][self.state['selected_printer']]
        if printer.get('type') != 'brother_ql':
            return None
        label = printer['label']
        label_w = int(label.get('width', 0))
        label_h = int(label.get('length', 0))
        label_id = f'{label_w}x{label_h}' if label_h > 0 else str(label_w)
        return pi.get_ql_native_pixels(label_id)

    def refresh_preview(self) -> None:
        rendered = lh.render_preview(
            state=self.state,
            fonts_by_name=self.fonts_by_name,
            config=self.config,
            target_px=self._get_native_pixels(),
        )
        self.preview.set_source(lh.pil_to_data_url(rendered))

    def update_state(self, **kwargs) -> None:
        self.state.update(kwargs)
        self.refresh_preview()

    # ------------------------------------------------------------------
    # Image source handlers
    # ------------------------------------------------------------------

    def get_cat_handler(self) -> None:
        log.debug('[magenta]Get Cat[/magenta] clicked')
        cat_image = lh.get_cat().convert('RGB')
        self.state['original_image'] = cat_image.copy()
        self.state['image'] = cat_image
        self.state['rotate_image_angle'] = 0
        self.state['image_source_kind'] = 'cat'
        self.refresh_preview()

    def get_dog_handler(self) -> None:
        log.debug('[magenta]Get Dog[/magenta] clicked')
        dog_image = lh.get_dog().convert('RGB')
        self.state['original_image'] = dog_image.copy()
        self.state['image'] = dog_image
        self.state['rotate_image_angle'] = 0
        self.state['image_source_kind'] = 'dog'
        self.refresh_preview()

    def get_dino_handler(self) -> None:
        log.debug('[magenta]Get Dino[/magenta] clicked')
        dino_image = lh.get_dino().convert('RGB')
        self.state['original_image'] = dino_image.copy()
        self.state['image'] = dino_image
        self.state['rotate_image_angle'] = 0
        self.state['image_source_kind'] = 'dino'
        self.refresh_preview()

    def clear_handler(self) -> None:
        log.debug('[magenta]Clear[/magenta] clicked')
        self.state['image'] = None
        self.state['original_image'] = None
        self.state['rotate_image_angle'] = 0
        self.state['image_source_kind'] = 'none'
        self.refresh_preview()

    def rotate_image_handler(self, angle: int) -> None:
        if self.state['original_image'] is None:
            return
        log.debug(f'[magenta]Rotate Image[/magenta] → {angle}°')
        self.state['rotate_image_angle'] = angle
        self.state['image'] = lh.rotate_image(self.state['original_image'], angle)
        self.refresh_preview()

    async def upload_handler(self, e) -> None:
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

    async def _start_camera_stream(self, device_id: str | None = None) -> str:
        """Start (or restart) the camera stream. Returns 'ok' or an error token."""
        import json
        constraint_video = (
            f'{{ deviceId: {{ exact: {json.dumps(device_id)} }} }}'
            if device_id
            else '{ facingMode: { ideal: \'environment\' } }'
        )
        result = await ui.run_javascript(f'''
            (async () => {{
                const video = document.getElementById('{self.webcam_video_id}');
                if (!video) return JSON.stringify({{error: 'missing-video'}});
                if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1')
                    return JSON.stringify({{error: 'insecure'}});
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
                    return JSON.stringify({{error: 'unsupported'}});
                try {{
                    if (video.srcObject) {{
                        video.srcObject.getTracks().forEach(t => t.stop());
                        video.srcObject = null;
                    }}
                    let stream;
                    try {{
                        stream = await navigator.mediaDevices.getUserMedia({{ video: {constraint_video} }});
                    }} catch (_) {{
                        stream = await navigator.mediaDevices.getUserMedia({{ video: true }});
                    }}
                    video.srcObject = stream;
                    await video.play();
                    const devices = await navigator.mediaDevices.enumerateDevices();
                    const cameras = devices
                        .filter(d => d.kind === 'videoinput')
                        .map((d, i) => ({{id: d.deviceId, label: d.label || `Camera ${{i + 1}}`}}));
                    const activeId = stream.getVideoTracks()[0]?.getSettings()?.deviceId || '';
                    return JSON.stringify({{ok: true, cameras, activeId}});
                }} catch (error) {{
                    const reason = error?.message || error?.name || 'unknown';
                    return JSON.stringify({{error: reason}});
                }}
            }})()
        ''')
        import json as _json
        try:
            return _json.loads(result)
        except Exception:
            return {'error': 'unknown'}

    async def open_webcam_dialog(self) -> None:
        self.webcam_dialog.open()
        data = await self._start_camera_stream()

        if data.get('ok'):
            log.info('Webcam stream started successfully.')
            cameras = data.get('cameras', [])
            active_id = data.get('activeId', '')
            options = {c['id']: c['label'] for c in cameras}
            if self.camera_select is not None:
                self.camera_select.options = options
                self.camera_select.value = active_id
                self.camera_select.visible = len(cameras) > 1
                self.camera_select.update()
            return

        await self.stop_webcam_stream()
        self.webcam_dialog.close()
        error = data.get('error', 'unknown')
        if error == 'insecure':
            ui.notify(
                'Camera access requires HTTPS. Please access this app over a secure connection.',
                type='negative',
            )
        elif error == 'unsupported':
            ui.notify('Browser webcam API is not supported on this device.', type='negative')
        else:
            ui.notify('Could not access webcam. Please allow camera permission.', type='negative')

    async def switch_camera_handler(self, e) -> None:
        device_id = e.value
        if not device_id:
            return
        data = await self._start_camera_stream(device_id=device_id)
        if not data.get('ok'):
            ui.notify('Could not switch camera.', type='negative')

    async def close_webcam_dialog(self) -> None:
        await self.stop_webcam_stream()
        if self.camera_select is not None:
            self.camera_select.visible = False
        self.webcam_dialog.close()

    async def capture_webcam_image(self) -> None:
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
    # Barcode generator
    # ------------------------------------------------------------------

    def barcode_data_change_handler(self, value: str) -> None:
        self.state['barcode_data'] = value
        if not value.strip():
            self.state['barcode_image'] = None
        self.refresh_preview()

    def generate_barcode_handler(self, _e) -> None:
        data = self.state.get('barcode_data', '').strip()
        if not data:
            ui.notify('Please enter barcode data first.', type='warning')
            return

        bc_type = self.state.get('barcode_type', 'Code128')
        show_value = self.state.get('barcode_show_value', True)
        attach_end = self.state.get('barcode_attach_end', False)
        log.debug(f'Generating {bc_type} barcode for: {data!r}')

        type_map = {
            'Code128': ('code128', {'includetext': True, 'height': 0.5}),
            'QR':      ('qrcode',  {}),
            'Aztec':   ('azteccode', {'eclevel': '23'}),
            'DataMatrix': ('datamatrix', {}),
        }
        tp_type, tp_options = type_map.get(bc_type, ('code128', {}))
        if bc_type == 'Code128' and not show_value:
            tp_options = {'height': 0.5}

        try:
            bc_img = _treepoem.generate_barcode(
                barcode_type=tp_type,
                data=data,
                options=tp_options,
            ).convert('RGB')
        except Exception as exc:
            log.error(f'Barcode generation failed: {exc}')
            ui.notify(f'Barcode error: {exc}', type='negative')
            return

        if attach_end:
            # Bake barcode below the existing image and clear the overlay
            size = max(1, self.state.get('barcode_size', 3))
            scaled = bc_img.resize((bc_img.width * size, bc_img.height * size), Image.NEAREST)
            base = self.state.get('original_image')
            if base is not None:
                combined_w = max(base.width, scaled.width)
                canvas = Image.new('RGB', (combined_w, base.height + scaled.height), 'white')
                canvas.paste(base, ((combined_w - base.width) // 2, 0))
                canvas.paste(scaled, ((combined_w - scaled.width) // 2, base.height))
                result = canvas
            else:
                result = scaled
            self.state['original_image'] = result.copy()
            self.state['image'] = result
            self.state['barcode_image'] = None
            self.state['rotate_image_angle'] = 0
            self.state['image_source_kind'] = 'barcode'
        else:
            # Store as live overlay — sliders take effect on every refresh
            self.state['barcode_image'] = bc_img

        self.refresh_preview()
        log.info(f'{bc_type} barcode ready (attach_end={attach_end}).')

    # ------------------------------------------------------------------
    # ZPL raw editor
    # ------------------------------------------------------------------

    def preview_zpl_handler(self, _e) -> None:
        log.debug('[magenta]Preview ZPL[/magenta] clicked')
        if self.state['selected_printer'] is None:
            ui.notify('No ZPL printer configured.', type='warning')
            return
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
        log.debug('[magenta]Send Raw ZPL[/magenta] clicked')
        if self.state['selected_printer'] is None:
            ui.notify('No ZPL printer configured.', type='warning')
            return
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
        log.info('[magenta]Stikka[/magenta] clicked')
        printer = self.config['printers'][self.state['selected_printer']]
        printer_type = printer['type']
        log.debug(f'Selected printer type: {printer_type}')

        img = lh.render_preview(
            state=self.state,
            fonts_by_name=self.fonts_by_name,
            config=self.config,
            target_px=self._get_native_pixels(),
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
