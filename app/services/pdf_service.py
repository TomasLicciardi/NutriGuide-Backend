from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime
from io import BytesIO
from typing import List, Dict, Any

class PDFService:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.primary_color = HexColor('#4CAF50')  # Verde tema de la app
        self.secondary_color = HexColor('#2196F3')  # Azul
        self.text_color = HexColor('#333333')
        
    def generate_history_pdf(self, user_data: Dict[str, Any], history_data: List[Dict[str, Any]]) -> BytesIO:
        """
        Genera un PDF con el historial de análisis del usuario
        """
        buffer = BytesIO()
        
        # Configurar documento
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )
        
        # Crear contenido
        story = []
        
        # Título principal
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=self.primary_color,
            fontName='Helvetica-Bold'
        )
        
        story.append(Paragraph("NUTRIGUIDE", title_style))
        story.append(Paragraph("Reporte de Historial de Análisis", 
                              ParagraphStyle('Subtitle', 
                                           parent=self.styles['Heading2'],
                                           fontSize=16,
                                           alignment=TA_CENTER,
                                           spaceAfter=20,
                                           textColor=self.text_color)))
        
        # Información del usuario
        user_info_style = ParagraphStyle(
            'UserInfo',
            parent=self.styles['Normal'],
            fontSize=12,
            spaceAfter=10,
            leftIndent=20,
            textColor=self.text_color
        )
        
        story.append(Paragraph(f"<b>Usuario:</b> {user_data.get('nombre', 'N/A')}", user_info_style))
        story.append(Paragraph(f"<b>Email:</b> {user_data.get('email', 'N/A')}", user_info_style))
        story.append(Paragraph(f"<b>Fecha de generación:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", user_info_style))
        story.append(Spacer(1, 20))
        
        # Estadísticas generales
        stats_style = ParagraphStyle(
            'Stats',
            parent=self.styles['Heading3'],
            fontSize=14,
            spaceAfter=15,
            textColor=self.secondary_color,
            fontName='Helvetica-Bold'
        )
        
        story.append(Paragraph("📊 Estadísticas Generales", stats_style))
        
        total_analisis = len(history_data)
        productos_unicos = len(set(item.get('nombre_producto', '') for item in history_data))
        
        stats_data = [
            ['Total de análisis realizados:', str(total_analisis)],
            ['Productos únicos analizados:', str(productos_unicos)],
            ['Primer análisis:', history_data[-1].get('fecha_analisis', 'N/A')[:10] if history_data else 'N/A'],
            ['Último análisis:', history_data[0].get('fecha_analisis', 'N/A')[:10] if history_data else 'N/A']
        ]
        
        stats_table = Table(stats_data, colWidths=[3*inch, 2*inch])
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), white),
            ('TEXTCOLOR', (0, 0), (-1, -1), self.text_color),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        
        story.append(stats_table)
        story.append(Spacer(1, 30))
        
        # Historial detallado
        story.append(Paragraph("📋 Historial Detallado", stats_style))
        story.append(Spacer(1, 10))
        
        if history_data:
            # Encabezados de la tabla
            table_data = [
                ['Fecha', 'Producto', 'Resultado', 'Recomendación']
            ]
            
            # Datos del historial
            for item in history_data[:20]:  # Limitar a 20 elementos para no sobrecargar
                fecha = item.get('fecha_analisis', '')[:10] if item.get('fecha_analisis') else 'N/A'
                producto = item.get('nombre_producto', 'N/A')
                resultado = self._get_resultado_texto(item.get('resultado_analisis'))
                recomendacion = self._truncate_text(item.get('recomendacion', 'N/A'), 50)
                
                table_data.append([fecha, producto, resultado, recomendacion])
            
            # Crear tabla
            history_table = Table(table_data, colWidths=[1.2*inch, 2*inch, 1.3*inch, 2.5*inch])
            history_table.setStyle(TableStyle([
                # Encabezado
                ('BACKGROUND', (0, 0), (-1, 0), self.primary_color),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                
                # Contenido
                ('TEXTCOLOR', (0, 1), (-1, -1), self.text_color),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#F5F5F5')]),
                
                # Bordes
                ('GRID', (0, 0), (-1, -1), 1, HexColor('#CCCCCC')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            
            story.append(history_table)
            
            if len(history_data) > 20:
                story.append(Spacer(1, 10))
                story.append(Paragraph(f"<i>Se muestran los primeros 20 análisis de {total_analisis} total.</i>", 
                                     self.styles['Normal']))
        else:
            story.append(Paragraph("No hay datos de historial disponibles.", self.styles['Normal']))
        
        # Pie de página
        story.append(Spacer(1, 30))
        footer_style = ParagraphStyle(
            'Footer',
            parent=self.styles['Normal'],
            fontSize=8,
            alignment=TA_CENTER,
            textColor=HexColor('#666666')
        )
        story.append(Paragraph("Este reporte fue generado automáticamente por Nutriguide", footer_style))
        story.append(Paragraph("Para más información visite nuestra aplicación móvil", footer_style))
        
        # Generar PDF
        doc.build(story)
        buffer.seek(0)
        
        return buffer
    
    def _get_resultado_texto(self, resultado: str) -> str:
        """Convierte el resultado del análisis a texto legible"""
        resultado_map = {
            'apto': '✅ Apto',
            'no_apto': '❌ No Apto',
            'precaucion': '⚠️ Precaución'
        }
        return resultado_map.get(resultado, resultado or 'N/A')
    
    def _truncate_text(self, text: str, max_length: int) -> str:
        """Trunca el texto si es muy largo"""
        if not text:
            return 'N/A'
        return text[:max_length] + '...' if len(text) > max_length else text
