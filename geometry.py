#!/usr/bin/env python3


import json
import requests

from utils import parse_map


def extract_points(path):
    subpaths = [i.lstrip('M') for i in path.rstrip('Z').split('Z')]
    contours = []
    for sp in subpaths:
        coords = [i.split(',') for i in sp.split('l')]
        x, y = map(float, coords[0])
        contour = [(x, y)]
        for c in coords[1:]:
            x += float(c[0])
            y += float(c[1])
            contour.append((x, y))
        contours.append(contour)
    return contours


def find_centroid(points):
    maxx = max(i[0] for i in points)
    minx = min(i[0] for i in points)
    maxy = max(i[1] for i in points)
    miny = min(i[1] for i in points)
    return [(maxx + minx) / 2, (maxy + miny) / 2]


def flatten(contours):
    return {i for contour in contours for i in contour}


def main():
    map_data = parse_map(requests.get('https://worldroulette.ru/world_mill_ru.js').text)
    centroids = {r: find_centroid(flatten(extract_points(v['path']))) for r, v in map_data.items()}
    with open('centroids.json', 'w') as f:
        json.dump(centroids, f, sort_keys=True)
    print('Centroids generated')


if __name__ == '__main__':
    main()
