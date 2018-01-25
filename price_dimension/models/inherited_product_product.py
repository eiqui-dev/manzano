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

import odoo
from odoo import models, fields, api, tools, SUPERUSER_ID
import odoo.addons.decimal_precision as dp
import logging
_logger = logging.getLogger(__name__)


class product_product(models.Model):
    _inherit = 'product.product'

    @api.depends('attribute_value_ids')
    def _get_price_extra(self):
        result = super(product_product, self)._get_price_extra()
        for product in self:
            price_extra = 0.0
            for variant_id in product.attribute_value_ids:
                if variant_id.price_extra_type != 'standard':
                    continue
                for price_id in variant_id.price_ids:
                    if price_id.product_tmpl_id.id == product.product_tmpl_id.id:
                        price_extra += price_id.price_extra
            result[product.id] = price_extra
        return result

    @api.model
    def origin_check_sale_dim_values(self, width, height):
        if self.sale_price_type in ['table_1d', 'table_2d']:
            product_prices_table_obj = self.env['product.prices_table']
            norm_width = self.origin_normalize_sale_width_value(width)
            if self.sale_price_type == 'table_2d':
                norm_height = self.origin_normalize_sale_height_value(height)
                return product_prices_table_obj.search_count([('sale_product_tmpl_id', '=', self.product_tmpl_id.id),
                                                              ('pos_x', '=', norm_width),
                                                              ('pos_y', '=', norm_height),
                                                              ('value', '!=', 0)]) > 0
            return product_prices_table_obj.search_count([('sale_product_tmpl_id', '=', self.product_tmpl_id.id),
                                                          ('pos_x', '=', norm_width),
                                                          ('value', '!=', 0)]) > 0
        elif self.sale_price_type == 'area':
            return width >= self.sale_price_area_min_width and width <= self.sale_price_area_max_width and height >= self.sale_price_area_min_height and height <= self.sale_price_area_max_height
        return True

    @api.model
    def origin_normalize_sale_width_value(self, width):
        headers = self.get_sale_price_table_headers()
        norm_val = width
        for index in range(len(headers['x'])-1):
            if width > headers['x'][index] and width <= headers['x'][index+1]:
                norm_val = headers['x'][index+1]
        return norm_val

    @api.model
    def origin_normalize_sale_height_value(self, height):
        headers = self.get_sale_price_table_headers()
        norm_val = height
        for index in range(len(headers['y'])-1):
            if height > headers['y'][index] and height <= headers['y'][index+1]:
                norm_val = headers['y'][index+1]
        return norm_val

    @api.depends('attribute_value_ids.price_ids.price_extra', 'attribute_value_ids.price_ids.product_tmpl_id')
    def _compute_lst_price(self):
        res = super(product_product, self)._compute_lst_price()
        product_uom_obj = self.env['product.uom']
        if 'uom' in self._context:
            to_uom = self.env['product.uom'].browse([self._context['uom']])
        for product in self:
            if to_uom:
                price = product.uom_id._compute_price(product.list_price, to_uom)
            else:
                price = product.list_price
            price += (price * product.price_extra_perc) / 100.0
            price += product.price_extra
            product.lst_price = price

    def _set_product_lst_price(self):
        super(product_product, self)._set_product_lst_price()
        product_uom_obj = self.pool.get('product.uom')
        for product in self:
            if self._context.get('uom'):
                value = product_uom_obj.browse(self._context['uom'])._compute_price(product.lst_price, product.uom_id)
            else:
                value = product.lst_price
            value -= (product.get_sale_price() * product.price_extra_perc) / 100.0
            value -= product.price_extra
            product.write({'list_price': value})

    @api.model
    def get_sale_price_table_headers(self):
        result = {'x': [0], 'y': [0]}
        for rec in self.sale_prices_table:
            result['x'].append(rec.pos_x)
            result['y'].append(rec.pos_y)
        result.update({
            'x': sorted(list(set(result['x']))),
            'y': sorted(list(set(result['y'])))
        })
        return result

    @api.model
    def get_sale_price(self):
        origin_width = self._context.get('width', False)
        origin_height = self._context.get('height', False)

        result = False
        if origin_width:
            product_prices_table_obj = self.env['product.prices_table']
            origin_width = self.origin_normalize_sale_width_value(origin_width)
            if self.sale_price_type == 'table_2d':
                origin_height = self.origin_normalize_sale_height_value(origin_height)
                res = product_prices_table_obj.search([
                    ('sale_product_tmpl_id', '=', self.product_tmpl_id.id),
                    ('pos_x', '=', origin_width),
                    ('pos_y', '=', origin_height)
                ], limit=1)
                result = res and res.value or False
            elif self.sale_price_type == 'table_1d':
                res = product_prices_table_obj.search([
                    ('sale_product_tmpl_id', '=', self.product_tmpl_id.id),
                    ('pos_x', '=', origin_width)
                ], limit=1)
                result = res and res.value or False
            elif self.sale_price_type == 'area':
                result = self.list_price * origin_width * origin_height
                result = max(self.sale_min_price_area, result)
        if not result:
            result = self.list_price
        return result

    def _get_price_extra_percentage(self):
        result = False
        for product in self:
            price_extra = 0.0
            for variant_id in product.attribute_value_ids:
                if variant_id.price_extra_type != 'percentage':
                    continue
                for price_id in variant_id.price_ids:
                    if price_id.product_tmpl_id.id == product.product_tmpl_id.id:
                        price_extra += price_id.price_extra
            result = price_extra
        return result

        price_extra = fields.Float(compute=_get_price_extra, type='float', string='Variant Extra Price', help="This is the sum of the extra price of all attributes", digits_compute=dp.get_precision('Product Price')),
        lst_price = fields.Function(compute=_product_lst_price, fnct_inv=_set_product_lst_price, type='float', string='Sale Price', digits_compute=dp.get_precision('Product Price')),

        price_extra_perc = fields.Function(compute=_get_price_extra_percentage, type='float', string='Variant Extra Price Percentage', help="This is the percentage of the extra price of all attributes", digits_compute=dp.get_precision('Product Price')),
    }
