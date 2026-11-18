"""Screenshot editor strings, independent of optional speech components."""

_EN = {
    "title": "Mouser Screenshot Editor",
    "select": "Select / crop", "rect": "Rectangle", "ellipse": "Ellipse",
    "arrow": "Arrow", "pen": "Pen", "text": "Text", "number": "Number",
    "mosaic": "Mosaic", "redact": "Solid conceal",
    "color": "Color", "width": "Stroke", "font": "Font size", "block": "Mosaic block",
    "undo": "Undo", "redo": "Redo", "crop": "Apply crop", "reset_crop": "Full image",
    "copy": "Copy", "save": "Save", "save_as": "Save as…", "pin": "Pin",
    "done": "Finish", "cancel": "Cancel", "fit": "Fit", "actual": "100%",
    "hint": "Drag to annotate. Crop: drag a box, move it or drag its handles, then Apply crop. Enter finishes; Esc cancels.",
    "selection_hint": "Drag to select; move selection / drag handles to resize. Enter or double-click to edit; Esc cancels.",
    "select_text": "Enter annotation text", "text_label": "Text (plain text):",
    "copied": "Screenshot copied to clipboard", "saved": "Screenshot saved to {path}",
    "cancelled": "Screenshot cancelled", "failed": "Screenshot failed: {error}",
    "busy": "Finish the current screenshot selection first",
    "pinned": "Screenshot pinned; drag to move, wheel to zoom, right-click to close.",
    "pin_hint": "Drag to move · Wheel to zoom · Right-click to close",
    "size": "{width} × {height} px",
    "privacy": "Mosaic can still reveal information. Use Solid conceal for sensitive text. Only the flattened image is copied/saved.",
    "mode_title": "Edit after capture (Windows)",
    "mode_desc": "Region and full-screen actions open the editor before delivery. Turn off for immediate copy/save. Existing shortcut mappings are unchanged.",
}
_ZH = {
    "title": "Mouser 截图编辑器",
    "select": "选区 / 裁剪", "rect": "矩形", "ellipse": "圆形",
    "arrow": "箭头", "pen": "画笔", "text": "文字", "number": "编号",
    "mosaic": "马赛克", "redact": "实色遮挡",
    "color": "颜色", "width": "线宽", "font": "字号", "block": "马赛克块",
    "undo": "撤销", "redo": "重做", "crop": "应用裁剪", "reset_crop": "完整图片",
    "copy": "复制", "save": "保存", "save_as": "另存为…", "pin": "贴图",
    "done": "完成", "cancel": "取消", "fit": "适应窗口", "actual": "100%",
    "hint": "拖动添加标注。裁剪：框选后可移动或拖动控制点，再点“应用裁剪”。Enter 完成，Esc 取消。",
    "selection_hint": "拖动框选；拖选区移动、拖控制点调整大小。Enter 或双击进入编辑，Esc 取消。",
    "select_text": "输入标注文字", "text_label": "文字（纯文本）：",
    "copied": "截图已复制到剪贴板", "saved": "截图已保存到 {path}",
    "cancelled": "截图已取消", "failed": "截图失败：{error}", "busy": "请先完成当前截图",
    "pinned": "已贴图：拖动移动，滚轮缩放，右键关闭。",
    "pin_hint": "拖动移动 · 滚轮缩放 · 右键关闭",
    "size": "{width} × {height} 像素",
    "privacy": "马赛克仍可能泄露信息，敏感文字建议用“实色遮挡”。复制和保存只输出合成后的图片。",
    "mode_title": "截图后编辑（Windows）",
    "mode_desc": "区域和全屏截图先进入编辑器，再复制或保存。关闭后恢复立即输出；不改变已有快捷键绑定。",
}
_TW = {
    "title": "Mouser 截圖編輯器",
    "select": "選區 / 裁剪", "rect": "矩形", "ellipse": "圓形", "arrow": "箭頭",
    "pen": "畫筆", "text": "文字", "number": "編號", "mosaic": "馬賽克",
    "redact": "實色遮擋", "color": "顏色", "width": "線寬", "font": "字號",
    "block": "馬賽克塊", "undo": "復原", "redo": "重做", "crop": "套用裁剪",
    "reset_crop": "完整圖片", "copy": "複製", "save": "儲存", "save_as": "另存新檔…",
    "pin": "貼圖", "done": "完成", "cancel": "取消", "fit": "適應視窗", "actual": "100%",
    "hint": "拖曳新增標註。裁剪：框選後可移動或拖曳控制點，再按「套用裁剪」。Enter 完成，Esc 取消。",
    "selection_hint": "拖曳框選；拖選區移動、拖控制點調整大小。Enter 或雙擊進入編輯，Esc 取消。",
    "select_text": "輸入標註文字", "text_label": "文字（純文字）：",
    "copied": "截圖已複製到剪貼簿", "saved": "截圖已儲存至 {path}",
    "cancelled": "截圖已取消", "failed": "截圖失敗：{error}", "busy": "請先完成目前截圖",
    "pinned": "已貼圖：拖曳移動，滾輪縮放，右鍵關閉。",
    "pin_hint": "拖曳移動 · 滾輪縮放 · 右鍵關閉",
    "size": "{width} × {height} 像素",
    "privacy": "馬賽克仍可能洩露資訊，敏感文字建議用「實色遮擋」。複製與儲存只輸出合成圖片。",
    "mode_title": "截圖後編輯（Windows）",
    "mode_desc": "區域與全螢幕截圖先進入編輯器，再複製或儲存。關閉後恢復立即輸出；不改變既有快捷鍵綁定。",
}
_EN.update({
    "select": "Select (default)",
    "pointer_hint": "Select (default): normal mouse pointer, not a crop tool; drag edge handles to resize",
    "hand": "Move selection: click, then drag anywhere inside; the screenshot stays frozen",
    "magnifier": "Magnifier", "scroll": "Scrolling capture · auto stitch",
    "scroll_pause": "Pause", "scroll_resume": "Resume",
    "scroll_viewport_detected": "Using the detected scrolling content only; fixed panels are excluded. Scroll down slowly, then click the checkmark.",
    "scroll_listening": "Auto stitching · Scroll down slowly in the original window",
    "scroll_paused": "Paused · Finish keeps accepted content; Resume continues capture",
    "scroll_undo_paused": "Undone and paused. Scroll back to overlap the last accepted content before resuming.",
    "scroll_finish_partial": "Last view could not be joined. Paused: scroll back and Resume, or Finish again to keep accepted content only.",
    "scroll_toolbar_overlap": "Paused: capture exclusion unavailable. Move this toolbar outside the selected region, then Resume.",
    "scroll_progress": "{count} updates · {width} × {height} px",
    "scroll_overlap": "Cannot join this view. Scroll back slightly to restore overlap; avoid fixed bars and animations. Existing capture is kept.",
    "scroll_unchanged": "No change found: scroll down before appending. Nothing was appended.",
    "scroll_size": "Capture size changed; restore the original viewport.",
    "scroll_small": "Choose a content region at least 40 × 80 px.",
    "scroll_limit": "Paused at capture limit (500 updates, 20,000 px height or 32 megapixels). Finish this capture.",
    "scroll_single_screen": "Scrolling capture currently requires a region on one monitor.",
    "scroll_capture_error": "Scrolling capture failed; the existing stitched image is retained.",
})
_ZH.update({
    "magnifier": "局部放大镜", "scroll": "滚动长截图 · 自动拼接",
    "scroll_pause": "暂停", "scroll_resume": "继续",
    "scroll_viewport_detected": "已限定到可滚动正文，固定面板不进入长图。在正文缓慢向下滚动，结束时点对勾。",
    "scroll_listening": "自动拼接中 · 请在原窗口缓慢向下滚动",
    "scroll_paused": "已暂停 · 点对勾保留已有长图，点继续恢复捕获",
    "scroll_undo_paused": "已撤销并暂停。请先向上回滚，与最后保留的内容重新衔接，再点继续。",
    "scroll_finish_partial": "最后一段未接上，已暂停。请回滚后继续；或再点对勾，仅保留已拼接部分。",
    "scroll_toolbar_overlap": "已暂停：系统无法排除控制条。请把本窗口移出截图选区，再点继续。",
    "scroll_progress": "{count} 次更新 · {width} × {height} 像素",
    "scroll_overlap": "当前画面未接上，请往回滚一点恢复重叠，并避开固定栏和动画；已有长图不变。",
    "scroll_unchanged": "画面没有变化，请向下滚动后再追加；本次未追加。",
    "scroll_size": "截图尺寸发生变化，请恢复原选区。",
    "scroll_small": "请选择至少 40 × 80 像素的内容区域。",
    "scroll_limit": "达到长截图上限，已暂停（500 次更新、高 20000 像素或 3200 万像素），请点对勾完成。",
    "scroll_single_screen": "长截图暂时只支持位于单个显示器内的选区。",
    "scroll_capture_error": "长截图捕获失败，已有拼接结果保持不变。",
})
_TW.update({
    "magnifier": "局部放大鏡", "scroll": "捲動長截圖 · 自動拼接",
    "scroll_pause": "暫停", "scroll_resume": "繼續",
    "scroll_viewport_detected": "已限定到可捲動正文，固定面板不進入長圖。在正文緩慢向下捲動，結束時按勾號。",
    "scroll_listening": "自動拼接中 · 請在原視窗緩慢向下捲動",
    "scroll_paused": "已暫停 · 按勾號保留既有長圖，按繼續恢復捕獲",
    "scroll_undo_paused": "已復原並暫停。請先向上捲回，與最後保留的內容重新銜接，再按繼續。",
    "scroll_finish_partial": "最後一段未接上，已暫停。請捲回後繼續；或再按勾號，僅保留已拼接部分。",
    "scroll_toolbar_overlap": "已暫停：系統無法排除控制列。請將本視窗移出截圖選區，再按繼續。",
    "scroll_progress": "{count} 次更新 · {width} × {height} 像素",
    "scroll_overlap": "目前畫面未接上，請往回捲一點恢復重疊，並避開固定列和動畫；既有長圖不變。",
    "scroll_unchanged": "畫面沒有變化，請向下捲動後再追加；本次未追加。",
    "scroll_size": "截圖尺寸發生變化，請恢復原選區。",
    "scroll_small": "請選擇至少 40 × 80 像素的內容區域。",
    "scroll_limit": "達到長截圖上限，已暫停（500 次更新、高 20000 像素或 3200 萬像素），請按勾號完成。",
    "scroll_single_screen": "長截圖目前只支援位於單個螢幕內的選區。",
    "scroll_capture_error": "長截圖捕獲失敗，既有拼接結果保持不變。",
})
for strings, selection in (
    (_EN, "Hover/click snaps to a visible top-level window; drag selects freely. Enter/double-click edits. S starts auto-stitch scrolling capture; M toggles magnifier; A toggles snapping; Esc cancels."),
    (_ZH, "悬停/单击选窗口，拖动自由框选；Enter/双击进入编辑。S 开始自动拼接长截图；M 切换放大镜；A 切换窗口识别；Esc 取消。"),
    (_TW, "懸停/單擊選視窗，拖曳自由框選；Enter/雙擊進入編輯。S 開始自動拼接長截圖；M 切換放大鏡；A 切換視窗辨識；Esc 取消。"),
):
    strings["selection_hint"] = selection

_EN.update({
    "shape": "Shapes", "more": "More", "help": "Help", "preview": "Preview",
    "finish_copy": "Copy & finish", "finish_save": "Save & finish",
    "compact_selection_hint": "Drag a region or click a window. Release to annotate · Esc cancels",
    "compact_help": "The default arrow is a normal pointer, not a crop tool: dragging blank areas does not reselect. Click the hand, then drag inside the selection to move it; edges still resize. Right-click or Select leaves drawing/move mode. Enter finishes; Esc cancels. Ctrl+Z undoes. Text: Ctrl+Enter commits; double-click text to edit. More → Text selection enables drag-to-copy text. Original buttons in the frozen image cannot be clicked.",
    "inline_hint": "Enter: new line · Ctrl+Enter: apply · Esc: discard this text",
    "scroll_before_marks": "Start scrolling before annotating. Undo marks first.",
    "scroll_hint": "Scroll down slowly in the original window; stitching is automatic. Keep overlap, avoid fixed bars. Click the checkmark when finished.",
})
_ZH.update({
    "shape": "形状", "more": "更多", "help": "帮助", "preview": "预览",
    "finish_copy": "完成并复制", "finish_save": "完成并保存",
    "compact_selection_hint": "拖动框选或单击选窗口，松开即可标注 · Esc 取消",
    "compact_help": "默认箭头是普通鼠标指针，不是框选工具；拖空白处不会重新划框。点选小手后在选区内拖动选框，边缘控制点仍可调整范围。右键或点“选择”退出标注／移动。Enter 完成，Esc 取消，Ctrl+Z 撤销。标注文字用 Ctrl+Enter 确认，双击修改。“更多 → 文字选择”可启用拖选复制；冻结图片中的原按钮不能点击。",
    "inline_hint": "Enter 换行 · Ctrl+Enter 确认 · Esc 放弃本次文字",
    "scroll_before_marks": "请先长截图再标注；已有标注请先撤销。",
    "scroll_hint": "在原窗口缓慢向下滚动，自动捕获并拼接；保留重叠、避开固定栏，结束时点对勾。",
})
_TW.update({
    "shape": "形狀", "more": "更多", "help": "說明", "preview": "預覽",
    "finish_copy": "完成並複製", "finish_save": "完成並儲存",
    "compact_selection_hint": "拖曳框選或單擊選視窗，放開即可標註 · Esc 取消",
    "compact_help": "預設箭頭是普通滑鼠指標，不是框選工具；拖曳空白處不會重新劃框。點選小手後在選區內拖曳選框，邊緣控制點仍可調整範圍。右鍵或按「選擇」退出標註／移動。Enter 完成，Esc 取消，Ctrl+Z 復原。標註文字用 Ctrl+Enter 確認，雙擊修改。「更多 → 文字選取」可啟用拖選複製；凍結圖片中的原按鈕不能點擊。",
    "inline_hint": "Enter 換行 · Ctrl+Enter 確認 · Esc 放棄本次文字",
    "scroll_before_marks": "請先長截圖再標註；既有標註請先復原。",
    "scroll_hint": "在原視窗緩慢向下捲動，自動捕獲並拼接；保留重疊、避開固定列，結束時按勾號。",
})

_EN.update({
    "scroll_live_preview": "Live scrolling screenshot preview",
    "scroll_hint": "Scroll down in the original window. Live preview updates automatically. Checkmark finishes; Esc cancels.",
    "scroll_finish_partial": "Last view not joined. Scroll back slightly to recover; or click Finish again to keep the preview only.",
    "scroll_toolbar_overlap": "Move this panel outside the capture region. Capture will resume automatically.",
    "scroll_paused": "Capture stopped · Checkmark keeps the current preview",
})
_ZH.update({
    "scroll_live_preview": "长截图实时预览",
    "scroll_hint": "在原窗口向下滚动，面板实时预览拼接结果；对勾完成，Esc 取消。",
    "scroll_finish_partial": "最后一段未接上。往回滚一点可继续识别；或再点对勾，仅保留预览里的内容。",
    "scroll_toolbar_overlap": "请把本面板移出截图选区，随后会自动继续。",
    "scroll_paused": "已停止捕获 · 点对勾保留当前预览",
})
_TW.update({
    "scroll_live_preview": "長截圖即時預覽",
    "scroll_hint": "在原視窗向下捲動，自動更新即時預覽；勾號完成，Esc 取消。",
    "scroll_finish_partial": "最後一段未接上。往回捲一點可繼續辨識；或再按勾號，僅保留預覽中的內容。",
    "scroll_toolbar_overlap": "請將本面板移出截圖選區，隨後會自動繼續。",
    "scroll_paused": "已停止捕獲 · 按勾號保留目前預覽",
})

_EN.update({
    "pin_drag": "Drag the hand to move the screenshot",
    "pin_close": "Close pinned screenshot",
    "pin_hint": "Drag the hand to move · Wheel to scroll · Ctrl+wheel to zoom · Copy keeps full resolution",
    "pinned": "Screenshot fixed on screen; drag the hand to move it. Copy keeps full resolution.",
    "mode_desc": "Select is the default. Click the hand, then drag inside the selection to move its bounds over the frozen screenshot. Finish to copy/save. Pin remains a separate freely movable image. Existing shortcuts are unchanged.",
})
_ZH.update({
    "select": "选择（默认）",
    "pointer_hint": "选择（默认）：普通鼠标指针，不重新框选；拖边缘控制点可调整范围",
    "hand": "移动选区：点选小手后，在选区内任意位置拖动；画面保持冻结",
    "pin_drag": "拖动小手移动截图",
    "pin_close": "关闭固定截图",
    "pin_hint": "拖动小手移动 · 滚轮查看长图 · Ctrl+滚轮缩放 · 复制保留原始清晰度",
    "pinned": "截图已固定显示，可拖动小手移动；复制保留原始清晰度。",
    "mode_desc": "截图默认使用“选择”；点选小手后，在选区内任意位置拖动选框，背景保持冻结。完成后复制或保存；贴图独立且可自由移动，不改变已有快捷键绑定。",
})
_TW.update({
    "select": "選擇（預設）",
    "pointer_hint": "選擇（預設）：普通滑鼠指標，不重新框選；拖邊緣控制點可調整範圍",
    "hand": "移動選區：點選小手後，在選區內任意位置拖曳；畫面保持凍結",
    "pin_drag": "拖曳小手移動截圖",
    "pin_close": "關閉固定截圖",
    "pin_hint": "拖曳小手移動 · 滾輪查看長圖 · Ctrl+滾輪縮放 · 複製保留原始清晰度",
    "pinned": "截圖已固定顯示，可拖曳小手移動；複製保留原始清晰度。",
    "mode_desc": "截圖預設使用「選擇」；點選小手後，在選區內任意位置拖曳選框，背景保持凍結。完成後複製或儲存；貼圖獨立且可自由移動，不改變既有快捷鍵綁定。",
})

_EN.update({
    "live_source_changed": "Original window moved, closed, minimized or switched. Live interaction paused; start a new screenshot.",
    "live_hint": "Live: drag text → Ctrl+C · Buttons work · Drag this bar to move · × exits",
    "live_pointer_hint": "Select original text inside the frame (experimental)",
    "live_finish_copy": "Copy current image & finish",
    "live_finish_save": "Save current image & finish",
    "live_copy_image": "Copy current image (not selected text)",
    "live_marks": "Annotations kept frozen. Undo all marks to select original text, or start a new screenshot.",
    "live_unavailable": "Live interaction unavailable: safe capture exclusion could not be enabled. Screenshot stays frozen.",
    "live_capture_failed": "Live refresh failed or displays changed. Kept the frozen image; this output was cancelled. Start a new screenshot.",
})
_ZH.update({
    "live_source_changed": "原窗口已移动、关闭、最小化或切换，已暂停框内交互，请重新截图。",
    "live_hint": "原窗口：拖选文字 → Ctrl+C · 按钮会响应 · 拖此栏移开 · × 退出",
    "live_pointer_hint": "在框内选择原文（实验功能）",
    "live_finish_copy": "复制当前图片并完成",
    "live_finish_save": "保存当前图片并完成",
    "live_copy_image": "复制当前图片（不是选中文字）",
    "live_marks": "已有标注，当前保持冻结；撤销全部标注后可选择原文，或重新截图。",
    "live_unavailable": "暂不能进入原窗口交互：系统未能安全排除截图工具，已保持冻结。",
    "live_capture_failed": "实时捕获失败或显示器布局改变，已保留冻结画面并取消本次输出，请重新截图。",
})
_TW.update({
    "live_source_changed": "原視窗已移動、關閉、最小化或切換，已暫停框內互動，請重新截圖。",
    "live_hint": "原視窗：拖選文字 → Ctrl+C · 按鈕會回應 · 拖此列移開 · × 退出",
    "live_pointer_hint": "在框內選擇原文（實驗功能）",
    "live_finish_copy": "複製目前圖片並完成",
    "live_finish_save": "儲存目前圖片並完成",
    "live_copy_image": "複製目前圖片（不是選取文字）",
    "live_marks": "已有標註，目前保持凍結；復原全部標註後可選擇原文，或重新截圖。",
    "live_unavailable": "暫不能進入原視窗互動：系統未能安全排除截圖工具，已保持凍結。",
    "live_capture_failed": "即時擷取失敗或顯示器配置改變，已保留凍結畫面並取消本次輸出，請重新截圖。",
})

_EN.update({
    "text_select": "Text selection",
    "text_select_missing": "The text-selection component is missing or damaged. Keep the 文字选择组件 folder beside Mouser.exe. No image is uploaded.",
    "text_select_working": "Preparing selectable text locally…",
    "text_select_ready": "Drag text → Ctrl+C · Ctrl+A selects all · Checkmark outputs the image. Check copied text for recognition errors.",
    "text_select_copied": "Selected text copied. Screenshot stays frozen.",
    "text_select_copy": "Copy selected text",
    "text_select_empty": "No text found. Try a clearer region.",
    "text_select_failed": "Could not prepare selectable text. Check the component or try a smaller region.",
    "text_select_cancelled": "Text selection cancelled.",
    "text_select_large": "Choose a screenshot below 32 megapixels.",
    "text_select_timeout": "Preparation exceeded 60 seconds; its isolated process has stopped.",
})
_ZH.update({
    "text_select": "文字选择",
    "text_select_missing": "文字选择组件缺失或损坏，请把完整的“文字选择组件”文件夹放在 Mouser.exe 旁边。不会上传截图。",
    "text_select_working": "正在本地准备可选择的文字…",
    "text_select_ready": "拖选文字 → Ctrl+C；Ctrl+A 全选。对勾仍输出图片，复制后请核对错字。",
    "text_select_copied": "选中文字已复制，截图保持冻结。",
    "text_select_copy": "复制选中文字",
    "text_select_empty": "没有找到文字，请选择更清晰的区域。",
    "text_select_failed": "暂时无法选择文字，请检查组件或尝试较小的区域。",
    "text_select_cancelled": "已取消文字选择。",
    "text_select_large": "请选择不超过 3200 万像素的截图。",
    "text_select_timeout": "准备文字超过 60 秒，已停止本次处理。",
})
_TW.update({
    "text_select": "文字選取",
    "text_select_missing": "文字選取元件遺失或損壞，請把完整的「文字选择组件」資料夾放在 Mouser.exe 旁邊。不會上傳截圖。",
    "text_select_working": "正在本機準備可選取的文字…",
    "text_select_ready": "拖選文字 → Ctrl+C；Ctrl+A 全選。勾號仍輸出圖片，複製後請核對錯字。",
    "text_select_copied": "選取文字已複製，截圖保持凍結。",
    "text_select_copy": "複製選取文字",
    "text_select_empty": "沒有找到文字，請選擇更清晰的區域。",
    "text_select_failed": "暫時無法選取文字，請檢查元件或嘗試較小的區域。",
    "text_select_cancelled": "已取消文字選取。",
    "text_select_large": "請選擇不超過 3200 萬像素的截圖。",
    "text_select_timeout": "準備文字超過 60 秒，已停止本次處理。",
})

_EN.update({
    "zoom_in": "Zoom in · Ctrl+wheel up",
    "zoom_out": "Zoom out · Ctrl+wheel down",
    "resize_window": "Drag this corner to resize the pinned window",
    "view_navigation": "Wheel to scroll · Ctrl+wheel to zoom around the pointer",
})
_ZH.update({
    "zoom_in": "放大 · Ctrl+滚轮向上",
    "zoom_out": "缩小 · Ctrl+滚轮向下",
    "resize_window": "拖动此角调整贴图窗口大小",
    "view_navigation": "滚轮上下浏览 · Ctrl+滚轮以鼠标所在位置缩放",
})
_TW.update({
    "zoom_in": "放大 · Ctrl+滾輪向上",
    "zoom_out": "縮小 · Ctrl+滾輪向下",
    "resize_window": "拖曳此角調整貼圖視窗大小",
    "view_navigation": "滾輪上下瀏覽 · Ctrl+滾輪以滑鼠所在位置縮放",
})

_EN["components_manage"] = "Screenshot components · Long capture / Text selection"
_ZH["components_manage"] = "截图组件 · 长截图 / 文字选择"
_TW["components_manage"] = "截圖元件 · 長截圖 / 文字選取"
_EN["text_select_missing"] = "Install or repair Text selection in Screenshot components. No image is uploaded."
_ZH["text_select_missing"] = "请在“截图组件”中安装或修复文字选择组件，不会上传图片。"
_TW["text_select_missing"] = "請在「截圖元件」中安裝或修復文字選取元件，不會上傳圖片。"

SCREENSHOT_TRANSLATIONS = {
    lang: {"screenshot." + key: value for key, value in strings.items()}
    for lang, strings in (("en", _EN), ("zh_CN", _ZH), ("zh_TW", _TW))
}


def screenshot_text(key, locale=None):
    if locale is not None:
        value = locale.tr("screenshot." + key)
        if value != "screenshot." + key:
            return value
    return _EN.get(key, key)
