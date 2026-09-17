"""Capture actual application UI with synthetic, non-private scientific data."""
import math
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QMessageBox
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from config import AppConfig,ConfigManager
from workspace import DesktopController
from dialogs import SettingsDialog
from text_editor import TextEditorDialog
from image_transforms import TransformSnapshot,ColorReplacement
from eps_renderer import EpsRenderer
from unittest.mock import patch


def create_demo(path):
    writer=PdfWriter()
    page=writer.add_blank_page(width=720,height=450)
    font=DictionaryObject({NameObject("/Type"):NameObject("/Font"),
                          NameObject("/Subtype"):NameObject("/Type1"),
                          NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")]=DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):font})})
    commands=["0 0 0 RG 1 w 90 90 m 640 90 l 640 355 l S",
              "90 90 m 90 355 l S"]
    def label(x,y,text,size=12):
        commands.append(f"0 0 0 rg BT /F1 {size} Tf 1 0 0 1 {x} {y} Tm ({text}) Tj ET")
    label(90,395,"Spectrum: before and after",24)
    label(90,373,"Synthetic data / EPS Live Viewer",11)
    for tick in range(6):
        x=90+110*tick
        commands.append(f".87 .9 .93 RG .5 w {x} 90 m {x} 350 l S")
        label(x-7,69,str(10+20*tick))
    for tick in range(5):
        y=90+60*tick
        commands.append(f".87 .9 .93 RG .5 w 90 {y} m 640 {y} l S")
        label(60,y-4,str(tick*25))
    label(297,33,"Energy (keV)",15)
    commands.append("0 0 0 rg BT /F1 15 Tf 0 1 -1 0 33 165 Tm (Intensity) Tj ET")
    for color,offset in (("0.09 0.44 0.82",0),("0.88 0.28 0.18",.6)):
        commands.append(color+" RG 2.5 w")
        for i in range(151):
            x=90+550*i/150
            y=115+180*math.exp(-((i/150-.35-offset*.09)/.18)**2)+20*math.sin(i/150*19+offset)
            commands.append(f"{x:.3f} {y:.3f} "+("m" if i==0 else "l"))
        commands.append("S")
    label(490,330,"Measured",12);label(490,307,"Reference",12)
    commands.extend([".09 .44 .82 RG 3 w 449 333 m 480 333 l S",
                     ".88 .28 .18 RG 3 w 449 310 m 480 310 l S"])
    stream=DecodedStreamObject();stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")]=writer._add_object(stream)
    writer.write(path);writer.close()


def main():
    app=QApplication.instance() or QApplication([])
    app.setOrganizationName("EPSProductScreenshots")
    app.setApplicationName("Demo")
    output=ROOT/"docs"/"screenshots"
    output.mkdir(parents=True,exist_ok=True)
    def wait(predicate=lambda:False,seconds=.5):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():return
            time.sleep(.01)
    def capture(widget,name):
        wait()
        pix=widget.grab()
        pix.scaledToWidth(1100,Qt.TransformationMode.SmoothTransformation).save(str(output/name))
    with tempfile.TemporaryDirectory(prefix="eps-demo-") as folder:
        folder=Path(folder)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(folder))
        source=folder/"Spectrum.pdf";create_demo(source)
        renderer=EpsRenderer()
        eps=folder/"Spectrum.eps"
        renderer.export_document(source,eps,TransformSnapshot(),1,1)
        manager=ConfigManager();manager.path=folder/"config.json"
        manager.save(AppConfig(auto_refresh=False,language="en",open_mode="tabs"))
        controller=DesktopController(manager);host=controller.new_window()
        host.resize(1120,740)
        view=host.add_document(eps)
        wait(lambda:view._current_pdf is not None,10)
        state=view._current_transforms()
        state.inverted=True
        state.replacements=[ColorReplacement("#E88F2E","#30D9C3",12)]
        view._apply_current_transforms()
        capture(host,"colors.png")
        state.inverted=False;state.replacements=[]
        view._apply_current_transforms()
        editor=TextEditorDialog(source,source,renderer,TransformSnapshot(),view)
        editor.resize(1120,740);editor.show()
        wait(lambda:not editor._busy,10)
        editor._start_edit(next(o for o in editor.objects if o.style.text.startswith("Spectrum:")))
        wait(lambda:not editor._busy,10)
        cursor=editor._active_item.textCursor()
        cursor.setPosition(10);cursor.setPosition(26,QTextCursor.MoveMode.KeepAnchor)
        editor._active_item.setTextCursor(cursor)
        editor._format("color","#008577");editor._format("bold",True)
        capture(editor,"text-editing.png")
        with patch.object(QMessageBox,"question",return_value=QMessageBox.StandardButton.Discard):
            editor.reject()
        settings=SettingsDialog(view._config,view,view._toolbar_options)
        settings.select_section("toolbar");settings.resize(760,640);settings.show()
        capture(settings,"toolbar.png");settings.reject()
        host.show_home();capture(host,"home.png")
        for i in range(host.tabs.count()):host.tabs.widget(i)._discard_on_close=True
        host.close();renderer.cache.cleanup()
    print(output)


if __name__=="__main__":
    main()
