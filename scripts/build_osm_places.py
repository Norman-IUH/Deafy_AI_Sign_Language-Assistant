"""Build the Pi's POI extract from a BBBike Saigon PBF using pyosmium."""
import argparse
from email.utils import parsedate_to_datetime
import json
from pathlib import Path

import osmium


class Places(osmium.SimpleHandler):
    amenities = {'restaurant', 'fast_food', 'cafe', 'pharmacy', 'hospital', 'atm'}
    fields = ('amenity', 'name', 'name:vi', 'cuisine', 'addr:full', 'addr:street',
              'addr:housenumber', 'addr:suburb', 'addr:district', 'addr:city', 'addr:province')

    def __init__(self):
        super().__init__()
        self.elements = []

    def add(self, tags, lat, lon):
        self.elements.append({'lat': lat, 'lon': lon,
                              'tags': {key: tags[key] for key in self.fields if key in tags}})

    def node(self, node):
        if node.tags.get('amenity') in self.amenities and (node.tags.get('name') or node.tags.get('name:vi')) and node.location.valid():
            self.add(node.tags, node.location.lat, node.location.lon)

    def way(self, way):
        if way.tags.get('amenity') not in self.amenities or not (way.tags.get('name') or way.tags.get('name:vi')):
            return
        coordinates = [(node.lat, node.lon) for node in way.nodes if node.location.valid()]
        if coordinates:
            lats, lons = zip(*coordinates)
            self.add(way.tags, (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('pbf', type=Path)
    parser.add_argument('last_modified', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    stamp = parsedate_to_datetime(args.last_modified.read_text().strip()).isoformat()
    places = Places()
    places.apply_file(args.pbf, locations=True, idx='sparse_mem_array')
    assert places.elements and any('addr:full' in item['tags'] or (
        'addr:housenumber' in item['tags'] and 'addr:street' in item['tags']) for item in places.elements)
    payload = {'snapshot_at': stamp, 'source': 'BBBike Saigon / OpenStreetMap', 'elements': places.elements}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'{len(places.elements)} POIs · {stamp}')
