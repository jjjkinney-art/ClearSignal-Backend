#!/usr/bin/env python3
"""Inventory retained HTML tables for source review; never emit financial claims.

Uses only local bytes. Indices follow opening-table order. Offsets are character
positions in the strict UTF-8 decoded HTML, not normalized text or byte offsets.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re


def clean(value):
    return re.sub(r'\s+', ' ', value).strip()


class TableInventory(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_starts = [0] + [match.end() for match in re.finditer('\n', source)]
        self.tables = []
        self.stack = []
        self.visible = []
        self.hidden_depth = 0

    def source_position(self):
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'script', 'style'}:
            self.hidden_depth += 1
        if tag == 'table':
            table = {'table_index': len(self.tables), 'html_start': self.source_position(),
                     'html_end': None, 'preceding_visible_context': clean(' '.join(self.visible))[-2500:],
                     'attributes': {k: v for k, v in attrs.items() if k == 'id'}, 'nested_table_indices': [], 'rows': [], '_row': None, '_cell': None}
            for parent in self.stack:
                parent['nested_table_indices'].append(table['table_index'])
            self.tables.append(table)
            self.stack.append(table)
        elif self.stack and tag == 'tr':
            table = self.stack[-1]
            row = {'html_start': self.source_position(), 'cells': []}
            table['rows'].append(row)
            table['_row'] = row
            table['_cell'] = None
        elif self.stack and tag in {'td', 'th'}:
            table = self.stack[-1]
            if table['_row'] is None:
                return
            cell = {'tag': tag, 'attributes': {k: v for k, v in attrs.items() if k in {'id', 'colspan', 'rowspan', 'headers', 'scope'}}, 'html_start': self.source_position(),
                    'html_end': None, 'text': '', 'inline_facts': [], '_parts': []}
            table['_row']['cells'].append(cell)
            table['_cell'] = cell
        elif self.stack and tag in {'ix:nonfraction', 'ix:nonnumeric'}:
            cell = self.stack[-1]['_cell']
            if cell is not None:
                cell['inline_facts'].append({'tag': tag, 'attributes': attrs,
                                             'html_start': self.source_position()})

    def handle_data(self, data):
        if self.hidden_depth:
            return
        self.visible.append(data)
        if self.stack and self.stack[-1]['_cell'] is not None:
            self.stack[-1]['_cell']['_parts'].append(data)

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        if not self.stack:
            return
        table = self.stack[-1]
        if tag in {'td', 'th'} and table['_cell'] is not None:
            cell = table['_cell']
            cell['html_end'] = self.source.index('>', self.source_position()) + 1
            cell['text'] = clean(' '.join(cell.pop('_parts')))
            table['_cell'] = None
        elif tag == 'tr':
            table['_row'] = None
        elif tag == 'table':
            table['html_end'] = self.source.index('>', self.source_position()) + 1
            self.stack.pop()


def inspect(body, receipt, table_index=None):
    digest = hashlib.sha256(body).hexdigest()
    if digest != receipt['body_sha256'] or len(body) != receipt['body_bytes']:
        raise ValueError('retained body does not match receipt hash and size')
    if receipt.get('media_type') != 'text/html':
        raise ValueError('receipt is not for HTML')
    source = body.decode('utf-8', errors='strict')
    parser = TableInventory(source)
    parser.feed(source)
    parser.close()
    if parser.stack or any(table['html_end'] is None for table in parser.tables):
        raise ValueError('unclosed table; refuse incomplete source map')
    summaries = []
    for table in parser.tables:
        for key in ('_row', '_cell'):
            table.pop(key)
        for row in table['rows']:
            if any(cell['html_end'] is None or '_parts' in cell for cell in row['cells']):
                raise ValueError('unclosed cell; refuse incomplete source map')
        text = clean(' '.join(cell['text'] for row in table['rows'] for cell in row['cells']))
        raw = source[table['html_start']:table['html_end']]
        table['raw_html_utf8_sha256'] = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        summaries.append({key: table[key] for key in ('table_index', 'html_start', 'html_end', 'raw_html_utf8_sha256')}
                         | {'row_count': len(table['rows']), 'nested_table_indices': table['nested_table_indices'], 'text_preview': text[:220]})
    if table_index is not None and not 0 <= table_index < len(parser.tables):
        raise ValueError('table index outside retained document')
    if table_index is not None and parser.tables[table_index]['nested_table_indices']:
        raise ValueError('selected table contains nested tables; choose an innermost table')
    return {'kind': 'unblinded_retained_html_table_source_map',
            'source': {'url': receipt.get('url'), 'body_sha256': digest, 'body_bytes': len(body),
                       'independent_origin_verification': receipt.get('independent_origin_verification', False)},
            'offset_basis': 'zero-based half-open character offsets in strict UTF-8 decoded raw HTML',
            'tables': summaries,
            'selected_table': parser.tables[table_index] if table_index is not None else None,
            'limitations': ['Inspection only: not production evidence admission, a financial claim or a new answer.',
                           'Cell text preserves source order; blank cells and colspan/rowspan attributes are not interpreted.',
                           'Inline attributes are inventoried, not independently validated or resolved against XBRL contexts and units.',
                           'No currency, scale, sign, period, segment identity, reconciliation or materiality is inferred.',
                           'Retained receipts bind these bytes; source authenticity and current availability are not established.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('body', type=Path)
    parser.add_argument('receipt', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--table-index', type=int)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('refuses to overwrite an existing source map')
    result = inspect(args.body.read_bytes(), json.loads(args.receipt.read_text()), args.table_index)
    with args.output.open('x') as target:
        json.dump(result, target, indent=2, ensure_ascii=False)
        target.write('\n')


if __name__ == '__main__':
    main()
