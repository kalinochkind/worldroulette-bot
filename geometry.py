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


def find_box(points):
    return [min(i[0] for i in points), min(i[1] for i in points),
            max(i[0] for i in points), max(i[1] for i in points)]


def find_centroid(box):
    return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]


def flatten(contours):
    return {i for contour in contours for i in contour}


BOX_EPS = 1

def boxes_intersect(box1, box2):
    x = box1[0] < box2[2] + BOX_EPS and box2[0] < box1[2] + BOX_EPS
    y = box1[1] < box2[3] + BOX_EPS and box2[1] < box1[3] + BOX_EPS
    return x and y


def find_neighbors(boxes):
    res = {}
    for k in boxes:
        res[k] = sorted(r for r in boxes if r != k and boxes_intersect(boxes[k], boxes[r]))
    return res


def main():
    map_data = parse_map(requests.get('https://worldroulette.ru/world_mill_ru.js').text)
    boxes = {r: find_box(flatten(extract_points(v['path']))) for r, v in map_data.items()}

    centroids = {r: find_centroid(v) for r, v in boxes.items()}
    with open('centroids.json', 'w') as f:
        json.dump(centroids, f, sort_keys=True)
    print('Centroids generated')

    neighbors = find_neighbors(boxes)
    with open('neighbors.json', 'w') as f:
        json.dump(neighbors, f, sort_keys=True)
    print('Neighbors generated')

if __name__ == '__main__':
    main()
