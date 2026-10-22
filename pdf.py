"""Mise en PDF de la lettre de déclaration (avec l'inventaire en annexe), via fpdf2."""

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from lettre import NOTE_ANNEXE, SEPARATEUR_ANNEXE, TITRE_ANNEXE

# Police DejaVu (licence libre, voir fonts/LICENSE-DejaVu.txt) : elle gère les accents, « », – et €
DOSSIER_POLICES = Path(__file__).parent / "fonts"
COLONNES_ANNEXE = ["N°", "Photo", "Pièce", "Objet", "Dommage constaté", "Certitude", "Valeur estimée"]
LARGEURS_ANNEXE = (10, 13, 28, 48, 82, 34, 30)  # en mm, page A4 paysage (257 mm utiles)


def lettre_en_pdf(lettre, inventaire=None):
    """Renvoie le PDF (en octets) de la lettre ; l'inventaire devient un tableau en annexe."""
    pdf = FPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(True, margin=20)
    pdf.add_font("DejaVu", "", str(DOSSIER_POLICES / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(DOSSIER_POLICES / "DejaVuSans-Bold.ttf"))

    pdf.add_page()
    pdf.set_font("DejaVu", size=10.5)
    corps = lettre.split(SEPARATEUR_ANNEXE)[0].strip()  # l'annexe texte est remplacée par un vrai tableau
    for bloc in corps.split("\n\n"):
        gras = bloc.startswith("Objet :")
        pdf.set_font("DejaVu", "B" if gras else "", 10.5)
        pdf.multi_cell(0, 5.5, bloc, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3.5)

    if inventaire:
        pdf.add_page(orientation="L")
        pdf.set_font("DejaVu", "B", 12)
        pdf.multi_cell(0, 7, TITRE_ANNEXE, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
        pdf.set_font("DejaVu", size=8.5)
        with pdf.table(col_widths=LARGEURS_ANNEXE, text_align="LEFT", line_height=4.5) as tableau:
            ligne = tableau.row()
            for titre in COLONNES_ANNEXE:
                ligne.cell(titre)
            for numero, l in enumerate(inventaire, start=1):
                ligne = tableau.row()
                for valeur in (numero, l["photo"] or "–", l["zone"], l["objet"], l["dommage"],
                               l["certitude"], l["valeur_estimee"]):
                    ligne.cell(str(valeur))
        pdf.ln(4)
        pdf.multi_cell(0, 4.5, NOTE_ANNEXE, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())
