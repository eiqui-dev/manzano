# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2017 Solucións Aloxa S.L. <info@aloxa.eu>
#                        Alexandre Díaz <alex@aloxa.eu>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from datetime import datetime
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from openerp.tools.translate import _
from openerp import models, fields, api, SUPERUSER_ID
from openerp.exceptions import ValidationError
import logging
_logger = logging.getLogger(__name__)


class procurement_order(models.Model):
    _inherit = 'procurement.order'
    
    # FIXME: Mejor usar atributos
    manzano_width = fields.Float(string="Width", required=False)
    manzano_height = fields.Float(string="Height", required=False)

    # BREAK INHERITANCE!!
    @api.multi
    def make_po(self):
        _logger.info("PASA PO")
        cache = {}
        res = []
        for procurement in self:
            suppliers = procurement.product_id.seller_ids.filtered(lambda r: not r.product_id or r.product_id == procurement.product_id)
            if not suppliers:
                procurement.message_post(body=_('No vendor associated to product %s. Please set one to fix this procurement.') % (procurement.product_id.name))
                continue
            supplier = suppliers[0]
            partner = supplier.name

            gpo = procurement.rule_id.group_propagation_option
            group = (gpo == 'fixed' and procurement.rule_id.group_id) or \
                    (gpo == 'propagate' and procurement.group_id) or False

            domain = (
                ('partner_id', '=', partner.id),
                ('state', '=', 'draft'),
                ('picking_type_id', '=', procurement.rule_id.picking_type_id.id),
                ('company_id', '=', procurement.company_id.id),
                ('dest_address_id', '=', procurement.partner_dest_id.id))
            if group:
                domain += (('group_id', '=', group.id),)

            if domain in cache:
                po = cache[domain]
            else:
                po = self.env['purchase.order'].search([dom for dom in domain])
                po = po[0] if po else False
                cache[domain] = po
            if not po:
                vals = procurement._prepare_purchase_order(partner)
                po = self.env['purchase.order'].create(vals)
                cache[domain] = po
            elif not po.origin or procurement.origin not in po.origin.split(', '):
                # Keep track of all procurements
                if po.origin:
                    if procurement.origin:
                        po.write({'origin': po.origin + ', ' + procurement.origin})
                    else:
                        po.write({'origin': po.origin})
                else:
                    po.write({'origin': procurement.origin})
            if po:
                res += [procurement.id]

            _logger.info("PASA PO 2")
            # Create Line
            po_line = False
            for line in po.order_line:
                _logger.info("PASA PO 2B")
                if line.product_id == procurement.product_id and line.product_uom == procurement.product_id.uom_po_id and line.manzano_width == procurement.purchase_line_id.manzano_width and line.manzano_height == procurement.purchase_line_id.manzano_height:
                    _logger.info("PASA PO 2C")
                    procurement_uom_po_qty = self.env['product.uom']._compute_qty_obj(procurement.product_uom, procurement.product_qty, procurement.product_id.uom_po_id)
                    seller = self.product_id._select_seller(
                        procurement.product_id,
                        partner_id=partner,
                        quantity=line.product_qty + procurement_uom_po_qty,
                        date=po.date_order and po.date_order[:10],
                        uom_id=procurement.product_id.uom_po_id)
                    
                    _logger.info("PASA PO 3")

                    if seller:
                        seller = seller.with_context(
                            width=line.manzano_width,
                            height=line.manzano_height
                        )
                        
                    _logger.info("PASA PO 4")

                    price_unit = self.env['account.tax']._fix_tax_included_price(seller.price, line.product_id.supplier_taxes_id, line.taxes_id) if seller else 0.0
                    if price_unit and seller and po.currency_id and seller.currency_id != po.currency_id:
                        price_unit = seller.currency_id.compute(price_unit, po.currency_id)

                    _logger.info("PASA PO 5")

                    po_line = line.write({
                        'product_qty': line.product_qty + procurement_uom_po_qty,
                        'price_unit': price_unit,
                        'procurement_ids': [(4, procurement.id)]
                    })
                    break
            if not po_line:
                _logger.info("PASA PO 56")
                vals = procurement._prepare_purchase_order_line(po, supplier)
                _logger.info("PASA PO 56 BB")
                _logger.info(self._context)
                _logger.info(vals)
                self.env['purchase.order.line'].create(vals)
                _logger.info("PASA PO 58")
        _logger.info("PASA PO FIN")
        return res

    @api.multi
    def _prepare_purchase_order_line(self, po, supplier):
        _logger.info("PASA PRESAA2")
        self.ensure_one()
        res = super(procurement_order, self)._prepare_purchase_order_line(po=po, supplier=supplier)
        
        _logger.info(self._context)
        _logger.info(self.manzano_height)
        
        product_id = self.product_id.with_context(
            width=self.purchase_line_id.manzano_width,
            height=self.purchase_line_id.manzano_height
        )

        procurement_uom_po_qty = self.env['product.uom']._compute_qty_obj(self.product_uom, self.product_qty, self.product_id.uom_po_id)
        seller = product_id._select_seller(
            product_id,
            partner_id=supplier.name,
            quantity=procurement_uom_po_qty,
            date=po.date_order and po.date_order[:10],
            uom_id=self.product_id.uom_po_id)

        if seller:
            seller = seller.with_context(
                width=self.purchase_line_id.manzano_width,
                height=self.purchase_line_id.manzano_height
            )

        taxes = product_id.supplier_taxes_id
        fpos = po.fiscal_position_id
        taxes_id = fpos.map_tax(taxes) if fpos else taxes
        if taxes_id:
            taxes_id = taxes_id.filtered(lambda x: x.company_id.id == self.company_id.id)

        price_unit = self.env['account.tax']._fix_tax_included_price(seller.price, product_id.supplier_taxes_id, taxes_id) if seller else 0.0
        if price_unit and seller and po.currency_id and seller.currency_id != po.currency_id:
            price_unit = seller.currency_id.compute(price_unit, po.currency_id)

        res.update({
            'price_unit': price_unit,
            'manzano_width': self.purchase_line_id.manzano_width,
            'manzano_height': self.purchase_line_id.manzano_height
        })

        return res
