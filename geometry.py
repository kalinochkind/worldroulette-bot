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


def find_box_neighbors(boxes):
    res = {}
    for k in boxes:
        res[k] = sorted(r for r in boxes if r != k and boxes_intersect(boxes[k], boxes[r]))
    return res


BORDER_DIST_EPS = 1


def segment_point_dist(x1, y1, x2, y2, x, y):
    den = ((x2 - x1) ** 2 + (y2 - y1) ** 2)
    if den == 0:
        return (x1 - x) ** 2 + (y1 - y) ** 2
    offset_coeff = ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / den
    if offset_coeff >= 1 or offset_coeff <= 0:
        return min((x1 - x) ** 2 + (y1 - y) ** 2, (x2 - x) ** 2 + (y2 - y) ** 2)
    projx, projy = x1 + (x2 - x1) * offset_coeff, y1 + (y2 - y1) * offset_coeff
    return (projx - x) ** 2 + (projy - y) ** 2


def segment_dist(x1, y1, x2, y2, x3, y3, x4, y4):
    return min(segment_point_dist(x1, y1, x2, y2, x3, y3),
               segment_point_dist(x1, y1, x2, y2, x4, y4),
               segment_point_dist(x3, y3, x4, y4, x1, y1),
               segment_point_dist(x3, y3, x4, y4, x2, y2))


def path_dist(path1, path2):
    return min(segment_dist(*a[0], *a[1], *b[0], *b[1]) for a in zip(path1, path1[1:] + path1[:1])
               for b in zip(path2, path2[1:] + path2[:1]))


def border_dist(paths1, paths2):
    return min(path_dist(a, b) for a in paths1 for b in paths2)


def are_neighbors(a, b):
    return border_dist(a, b) < BORDER_DIST_EPS


def main():
    map_data = parse_map(requests.get('https://worldroulette.ru/world_mill_ru.js').text)
    borders = {r: extract_points(v['path']) for r, v in map_data.items()}

    boxes = {r: find_box(flatten(v)) for r, v in borders.items()}
    centroids = {r: find_centroid(v) for r, v in boxes.items()}
    print('Centroids generated')
    box_neighbors = find_box_neighbors(boxes)
    print('Box neighbors generated')

    neighbors = {}
    for c in sorted(borders):
        print(c, end=' ', flush=True)
        neighbors[c] = sorted(i for i in box_neighbors[c] if are_neighbors(borders[c], borders[i]))
    print()
    print('Real neighbors generated')
    with open('neighbors.json', 'w') as f:
        json.dump(neighbors, f, sort_keys=True)

if __name__ == '__main__':
    main()
