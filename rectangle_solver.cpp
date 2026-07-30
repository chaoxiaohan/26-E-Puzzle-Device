#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <queue>
#include <string>
#include <thread>
#include <unordered_set>
#include <utility>
#include <vector>

struct Point {
    double x;
    double y;
};

struct Candidate {
    std::vector<Point> polygon;
    std::vector<std::uint64_t> mask;
    std::vector<std::uint64_t> core;
    int area = 0;
    int corners = 0;
};

struct State {
    std::vector<std::uint64_t> union_mask;
    std::vector<std::uint64_t> core_union;
    std::vector<int> choices;
    int covered = 0;
    int overlap = 0;
    int corners = 0;
    double proximity = 0.0;
    double contact = 0.0;
    double rank = 0.0;
};

static double polygon_area(const std::vector<Point>& polygon) {
    double value = 0.0;
    for (std::size_t index = 0; index < polygon.size(); ++index) {
        const Point& first = polygon[index];
        const Point& second = polygon[(index + 1) % polygon.size()];
        value += first.x * second.y - second.x * first.y;
    }
    return value * 0.5;
}

static double distance(const Point& first, const Point& second) {
    return std::hypot(first.x - second.x, first.y - second.y);
}

static bool point_in_polygon(
    double x,
    double y,
    const std::vector<Point>& polygon
) {
    bool inside = false;
    for (
        std::size_t first_id = 0, second_id = polygon.size() - 1;
        first_id < polygon.size();
        second_id = first_id++
    ) {
        const Point& first = polygon[first_id];
        const Point& second = polygon[second_id];
        if (
            (first.y > y) != (second.y > y)
            && x < (
                (second.x - first.x)
                * (y - first.y)
                / (second.y - first.y)
                + first.x
            )
        ) {
            inside = !inside;
        }
    }
    return inside;
}

static double cross(
    const Point& first,
    const Point& second,
    const Point& third
) {
    return (
        (second.x - first.x) * (third.y - first.y)
        - (second.y - first.y) * (third.x - first.x)
    );
}

static bool point_on_segment(
    const Point& point,
    const Point& start,
    const Point& end
) {
    if (std::abs(cross(start, end, point)) > 1e-7) {
        return false;
    }
    return (
        point.x >= std::min(start.x, end.x) - 1e-7
        && point.x <= std::max(start.x, end.x) + 1e-7
        && point.y >= std::min(start.y, end.y) - 1e-7
        && point.y <= std::max(start.y, end.y) + 1e-7
    );
}

static bool point_strictly_inside(
    const Point& point,
    const std::vector<Point>& polygon
) {
    for (std::size_t index = 0; index < polygon.size(); ++index) {
        if (point_on_segment(
            point,
            polygon[index],
            polygon[(index + 1) % polygon.size()]
        )) {
            return false;
        }
    }
    return point_in_polygon(point.x, point.y, polygon);
}

static bool polygons_overlap(
    const std::vector<Point>& first,
    const std::vector<Point>& second
) {
    for (std::size_t first_id = 0; first_id < first.size(); ++first_id) {
        const Point& first_start = first[first_id];
        const Point& first_end = first[
            (first_id + 1) % first.size()
        ];
        for (
            std::size_t second_id = 0;
            second_id < second.size();
            ++second_id
        ) {
            const Point& second_start = second[second_id];
            const Point& second_end = second[
                (second_id + 1) % second.size()
            ];
            double first_side = cross(
                first_start,
                first_end,
                second_start
            );
            double second_side = cross(
                first_start,
                first_end,
                second_end
            );
            double third_side = cross(
                second_start,
                second_end,
                first_start
            );
            double fourth_side = cross(
                second_start,
                second_end,
                first_end
            );
            if (
                first_side * second_side < -1e-9
                && third_side * fourth_side < -1e-9
            ) {
                return true;
            }
        }
    }
    for (const Point& point : first) {
        if (point_strictly_inside(point, second)) {
            return true;
        }
    }
    for (const Point& point : second) {
        if (point_strictly_inside(point, first)) {
            return true;
        }
    }
    return false;
}

static void set_bit(std::vector<std::uint64_t>& bits, int index) {
    bits[index >> 6] |= std::uint64_t(1) << (index & 63);
}

static bool get_bit(
    const std::vector<std::uint64_t>& bits,
    int index
) {
    return (
        bits[index >> 6]
        & (std::uint64_t(1) << (index & 63))
    ) != 0;
}

static int intersection_count(
    const std::vector<std::uint64_t>& first,
    const std::vector<std::uint64_t>& second
) {
    int count = 0;
    for (std::size_t index = 0; index < first.size(); ++index) {
        count += __builtin_popcountll(first[index] & second[index]);
    }
    return count;
}

static Candidate rasterize(
    const std::vector<Point>& polygon,
    int width,
    int height
) {
    Candidate candidate;
    candidate.polygon = polygon;
    int pixel_count = width * height;
    int word_count = (pixel_count + 63) / 64;
    candidate.mask.assign(word_count, 0);
    candidate.core.assign(word_count, 0);

    double minimum_x = polygon[0].x;
    double maximum_x = polygon[0].x;
    double minimum_y = polygon[0].y;
    double maximum_y = polygon[0].y;
    for (const Point& point : polygon) {
        minimum_x = std::min(minimum_x, point.x);
        maximum_x = std::max(maximum_x, point.x);
        minimum_y = std::min(minimum_y, point.y);
        maximum_y = std::max(maximum_y, point.y);
    }
    int start_x = std::max(0, int(std::floor(minimum_x)) - 1);
    int end_x = std::min(width - 1, int(std::ceil(maximum_x)) + 1);
    int start_y = std::max(0, int(std::floor(minimum_y)) - 1);
    int end_y = std::min(height - 1, int(std::ceil(maximum_y)) + 1);
    for (int y = start_y; y <= end_y; ++y) {
        for (int x = start_x; x <= end_x; ++x) {
            if (point_in_polygon(x + 0.5, y + 0.5, polygon)) {
                set_bit(candidate.mask, y * width + x);
                ++candidate.area;
            }
        }
    }

    for (int y = 1; y < height - 1; ++y) {
        for (int x = 1; x < width - 1; ++x) {
            bool keep = true;
            for (int offset_y = -1; offset_y <= 1 && keep; ++offset_y) {
                for (int offset_x = -1; offset_x <= 1; ++offset_x) {
                    if (!get_bit(
                        candidate.mask,
                        (y + offset_y) * width + x + offset_x
                    )) {
                        keep = false;
                        break;
                    }
                }
            }
            if (keep) {
                set_bit(candidate.core, y * width + x);
            }
        }
    }

    const Point corners[4] = {
        {0.0, 0.0},
        {double(width - 1), 0.0},
        {double(width - 1), double(height - 1)},
        {0.0, double(height - 1)},
    };
    for (int corner_id = 0; corner_id < 4; ++corner_id) {
        double nearest = std::numeric_limits<double>::infinity();
        for (const Point& point : polygon) {
            nearest = std::min(nearest, distance(point, corners[corner_id]));
        }
        if (nearest <= 3.5) {
            candidate.corners |= 1 << corner_id;
        }
    }
    return candidate;
}

static std::vector<Point> align_edge(
    const std::vector<Point>& polygon,
    int edge_id,
    const Point& target_start,
    const Point& target_end
) {
    const Point& source_start = polygon[edge_id];
    const Point& source_end = polygon[(edge_id + 1) % polygon.size()];
    double source_angle = std::atan2(
        source_end.y - source_start.y,
        source_end.x - source_start.x
    );
    double target_angle = std::atan2(
        target_start.y - target_end.y,
        target_start.x - target_end.x
    );
    double angle = target_angle - source_angle;
    double cosine = std::cos(angle);
    double sine = std::sin(angle);
    Point source_middle{
        (source_start.x + source_end.x) * 0.5,
        (source_start.y + source_end.y) * 0.5,
    };
    Point target_middle{
        (target_start.x + target_end.x) * 0.5,
        (target_start.y + target_end.y) * 0.5,
    };

    std::vector<Point> transformed;
    transformed.reserve(polygon.size());
    for (const Point& point : polygon) {
        double x = point.x - source_middle.x;
        double y = point.y - source_middle.y;
        transformed.push_back({
            x * cosine - y * sine + target_middle.x,
            x * sine + y * cosine + target_middle.y,
        });
    }
    return transformed;
}

static std::vector<Candidate> generate_candidates(
    const std::vector<Point>& polygon,
    int width,
    int height,
    int position_step
) {
    std::vector<Candidate> candidates;
    std::unordered_set<std::string> generated;
    for (int edge_id = 0; edge_id < int(polygon.size()); ++edge_id) {
        double edge_size = distance(
            polygon[edge_id],
            polygon[(edge_id + 1) % polygon.size()]
        );
        if (edge_size < 8.0) {
            continue;
        }
        for (int side = 0; side < 4; ++side) {
            double side_size = side < 2 ? width : height;
            if (edge_size > side_size + 2.5) {
                continue;
            }
            double maximum = std::max(0.0, side_size - edge_size);
            std::vector<double> positions;
            for (
                double position = 0.0;
                position <= maximum + 0.1;
                position += position_step
            ) {
                positions.push_back(position);
            }
            positions.push_back(0.0);
            positions.push_back(maximum);
            std::sort(positions.begin(), positions.end());
            positions.erase(
                std::unique(
                    positions.begin(),
                    positions.end(),
                    [](double first, double second) {
                        return std::abs(first - second) < 0.05;
                    }
                ),
                positions.end()
            );

            for (double position : positions) {
                Point first;
                Point second;
                if (side == 0) {
                    first = {position, 0.0};
                    second = {position + edge_size, 0.0};
                } else if (side == 1) {
                    first = {position, double(height - 1)};
                    second = {
                        position + edge_size,
                        double(height - 1),
                    };
                } else if (side == 2) {
                    first = {0.0, position};
                    second = {0.0, position + edge_size};
                } else {
                    first = {double(width - 1), position};
                    second = {
                        double(width - 1),
                        position + edge_size,
                    };
                }

                for (int reverse = 0; reverse < 2; ++reverse) {
                    std::vector<Point> transformed = align_edge(
                        polygon,
                        edge_id,
                        reverse == 0 ? first : second,
                        reverse == 0 ? second : first
                    );
                    bool inside = true;
                    for (Point& point : transformed) {
                        if (
                            point.x < -2.5
                            || point.y < -2.5
                            || point.x > width - 1 + 2.5
                            || point.y > height - 1 + 2.5
                        ) {
                            inside = false;
                            break;
                        }
                        point.x = std::clamp(
                            point.x,
                            0.0,
                            double(width - 1)
                        );
                        point.y = std::clamp(
                            point.y,
                            0.0,
                            double(height - 1)
                        );
                    }
                    if (!inside) {
                        continue;
                    }
                    Point center{0.0, 0.0};
                    for (const Point& point : transformed) {
                        center.x += point.x;
                        center.y += point.y;
                    }
                    center.x /= transformed.size();
                    center.y /= transformed.size();
                    std::string key = (
                        std::to_string(int(std::lround(center.x / 2.0)))
                        + ":"
                        + std::to_string(int(std::lround(center.y / 2.0)))
                        + ":"
                        + std::to_string(edge_id)
                        + ":"
                        + std::to_string(side)
                    );
                    if (!generated.insert(key).second) {
                        continue;
                    }
                    candidates.push_back(
                        rasterize(transformed, width, height)
                    );
                }
            }
        }
    }
    return candidates;
}

static double vertex_proximity(
    const std::vector<Point>& first,
    const std::vector<Point>& second
) {
    double nearest = std::numeric_limits<double>::infinity();
    for (const Point& first_point : first) {
        for (const Point& second_point : second) {
            nearest = std::min(
                nearest,
                distance(first_point, second_point)
            );
        }
    }
    double amount = std::max(0.0, 24.0 - nearest);
    return amount * amount;
}

static double internal_edge_match(
    const std::vector<Point>& first,
    const std::vector<Point>& second
) {
    double best = 0.0;
    for (std::size_t first_id = 0; first_id < first.size(); ++first_id) {
        const Point& first_start = first[first_id];
        const Point& first_end = first[(first_id + 1) % first.size()];
        double first_dx = first_end.x - first_start.x;
        double first_dy = first_end.y - first_start.y;
        double first_length = std::hypot(first_dx, first_dy);
        if (first_length < 5.0) {
            continue;
        }
        double unit_x = first_dx / first_length;
        double unit_y = first_dy / first_length;

        for (
            std::size_t second_id = 0;
            second_id < second.size();
            ++second_id
        ) {
            const Point& second_start = second[second_id];
            const Point& second_end = second[
                (second_id + 1) % second.size()
            ];
            double second_dx = second_end.x - second_start.x;
            double second_dy = second_end.y - second_start.y;
            double second_length = std::hypot(second_dx, second_dy);
            if (second_length < 5.0) {
                continue;
            }
            double parallel = std::abs(
                unit_x * second_dx / second_length
                + unit_y * second_dy / second_length
            );
            if (parallel < 0.985) {
                continue;
            }
            double start_offset = std::abs(
                unit_x * (second_start.y - first_start.y)
                - unit_y * (second_start.x - first_start.x)
            );
            double end_offset = std::abs(
                unit_x * (second_end.y - first_start.y)
                - unit_y * (second_end.x - first_start.x)
            );
            double line_offset = (start_offset + end_offset) * 0.5;
            if (line_offset > 3.5) {
                continue;
            }
            double projected_start = (
                (second_start.x - first_start.x) * unit_x
                + (second_start.y - first_start.y) * unit_y
            );
            double projected_end = (
                (second_end.x - first_start.x) * unit_x
                + (second_end.y - first_start.y) * unit_y
            );
            double overlap = (
                std::min(
                    first_length,
                    std::max(projected_start, projected_end)
                )
                - std::max(
                    0.0,
                    std::min(projected_start, projected_end)
                )
            );
            if (overlap <= 4.0) {
                continue;
            }
            double length_similarity = (
                std::min(first_length, second_length)
                / std::max(first_length, second_length)
            );
            best = std::max(
                best,
                overlap
                * length_similarity
                * (1.0 - line_offset / 3.5)
            );
        }
    }
    return best;
}

struct EdgeRecord {
    int piece_id;
    Point start;
    Point end;
    Point center;
    double length;
    int outer_side;
    std::vector<std::pair<double, double>> matches;
};

struct DetailedQuality {
    double internal = 0.0;
    double boundary = 0.0;
    double boundary_min = 0.0;
    double boundary_max_gap = 1.0;
    double boundary_angle_error = 0.0;
    double connected = 0.0;
};

static double interval_union_length(
    std::vector<std::pair<double, double>> intervals
) {
    if (intervals.empty()) {
        return 0.0;
    }
    std::sort(intervals.begin(), intervals.end());
    double total = 0.0;
    double start = intervals[0].first;
    double end = intervals[0].second;
    for (std::size_t index = 1; index < intervals.size(); ++index) {
        if (intervals[index].first <= end + 0.5) {
            end = std::max(end, intervals[index].second);
        } else {
            total += end - start;
            start = intervals[index].first;
            end = intervals[index].second;
        }
    }
    return total + end - start;
}

static double interval_max_gap_ratio(
    std::vector<std::pair<double, double>> intervals,
    double side_length
) {
    if (intervals.empty() || side_length <= 0.0) {
        return 1.0;
    }
    std::sort(intervals.begin(), intervals.end());
    double maximum_gap = std::max(0.0, intervals[0].first);
    double end = intervals[0].second;
    for (std::size_t index = 1; index < intervals.size(); ++index) {
        maximum_gap = std::max(
            maximum_gap,
            intervals[index].first - end
        );
        end = std::max(end, intervals[index].second);
    }
    maximum_gap = std::max(maximum_gap, side_length - end);
    return maximum_gap / side_length;
}

static DetailedQuality evaluate_detailed_quality(
    const std::vector<std::vector<Point>>& layout,
    int width,
    int height
) {
    std::vector<EdgeRecord> edges;
    std::vector<std::pair<double, double>> boundary_intervals[4];
    double boundary_angle_error = 0.0;
    for (int piece_id = 0; piece_id < int(layout.size()); ++piece_id) {
        const std::vector<Point>& polygon = layout[piece_id];
        Point center{0.0, 0.0};
        for (const Point& point : polygon) {
            center.x += point.x;
            center.y += point.y;
        }
        center.x /= polygon.size();
        center.y /= polygon.size();
        for (int edge_id = 0; edge_id < int(polygon.size()); ++edge_id) {
            const Point& start = polygon[edge_id];
            const Point& end = polygon[
                (edge_id + 1) % polygon.size()
            ];
            double length = distance(start, end);
            int outer_side = -1;
            if (
                std::max(std::abs(start.y), std::abs(end.y)) <= 3.5
            ) {
                outer_side = 0;
                boundary_intervals[0].push_back({
                    std::max(0.0, std::min(start.x, end.x)),
                    std::min(double(width - 1), std::max(start.x, end.x)),
                });
            } else if (
                std::max(
                    std::abs(start.y - height + 1),
                    std::abs(end.y - height + 1)
                ) <= 3.5
            ) {
                outer_side = 1;
                boundary_intervals[1].push_back({
                    std::max(0.0, std::min(start.x, end.x)),
                    std::min(double(width - 1), std::max(start.x, end.x)),
                });
            } else if (
                std::max(std::abs(start.x), std::abs(end.x)) <= 3.5
            ) {
                outer_side = 2;
                boundary_intervals[2].push_back({
                    std::max(0.0, std::min(start.y, end.y)),
                    std::min(double(height - 1), std::max(start.y, end.y)),
                });
            } else if (
                std::max(
                    std::abs(start.x - width + 1),
                    std::abs(end.x - width + 1)
                ) <= 3.5
            ) {
                outer_side = 3;
                boundary_intervals[3].push_back({
                    std::max(0.0, std::min(start.y, end.y)),
                    std::min(double(height - 1), std::max(start.y, end.y)),
                });
            }
            if (outer_side >= 0 && length > 1e-6) {
                double axis_error = (
                    outer_side <= 1
                    ? std::abs(end.y - start.y)
                    : std::abs(end.x - start.x)
                );
                boundary_angle_error = std::max(
                    boundary_angle_error,
                    std::asin(std::min(1.0, axis_error / length))
                    * 180.0 / std::acos(-1.0)
                );
            }
            edges.push_back({
                piece_id,
                start,
                end,
                center,
                length,
                outer_side,
                {},
            });
        }
    }

    unsigned int adjacency[4] = {0, 0, 0, 0};
    for (std::size_t first_id = 0; first_id < edges.size(); ++first_id) {
        EdgeRecord& first = edges[first_id];
        if (first.outer_side >= 0 || first.length < 5.0) {
            continue;
        }
        double first_unit_x = (
            first.end.x - first.start.x
        ) / first.length;
        double first_unit_y = (
            first.end.y - first.start.y
        ) / first.length;
        for (
            std::size_t second_id = first_id + 1;
            second_id < edges.size();
            ++second_id
        ) {
            EdgeRecord& second = edges[second_id];
            if (
                second.outer_side >= 0
                || second.piece_id == first.piece_id
                || second.length < 5.0
            ) {
                continue;
            }
            double second_unit_x = (
                second.end.x - second.start.x
            ) / second.length;
            double second_unit_y = (
                second.end.y - second.start.y
            ) / second.length;
            double parallel = std::abs(
                first_unit_x * second_unit_x
                + first_unit_y * second_unit_y
            );
            if (parallel < 0.99) {
                continue;
            }
            double start_offset = std::abs(
                first_unit_x * (second.start.y - first.start.y)
                - first_unit_y * (second.start.x - first.start.x)
            );
            double end_offset = std::abs(
                first_unit_x * (second.end.y - first.start.y)
                - first_unit_y * (second.end.x - first.start.x)
            );
            if ((start_offset + end_offset) * 0.5 > 3.5) {
                continue;
            }
            if (
                cross(first.start, first.end, first.center)
                * cross(first.start, first.end, second.center) >= 0.0
            ) {
                continue;
            }

            double second_start_on_first = (
                (second.start.x - first.start.x) * first_unit_x
                + (second.start.y - first.start.y) * first_unit_y
            );
            double second_end_on_first = (
                (second.end.x - first.start.x) * first_unit_x
                + (second.end.y - first.start.y) * first_unit_y
            );
            double first_match_start = std::max(
                0.0,
                std::min(second_start_on_first, second_end_on_first)
            );
            double first_match_end = std::min(
                first.length,
                std::max(second_start_on_first, second_end_on_first)
            );
            if (first_match_end - first_match_start <= 4.0) {
                continue;
            }

            double first_start_on_second = (
                (first.start.x - second.start.x) * second_unit_x
                + (first.start.y - second.start.y) * second_unit_y
            );
            double first_end_on_second = (
                (first.end.x - second.start.x) * second_unit_x
                + (first.end.y - second.start.y) * second_unit_y
            );
            double second_match_start = std::max(
                0.0,
                std::min(first_start_on_second, first_end_on_second)
            );
            double second_match_end = std::min(
                second.length,
                std::max(first_start_on_second, first_end_on_second)
            );
            first.matches.push_back({
                first_match_start,
                first_match_end,
            });
            second.matches.push_back({
                second_match_start,
                second_match_end,
            });
            adjacency[first.piece_id] |= 1u << second.piece_id;
            adjacency[second.piece_id] |= 1u << first.piece_id;
        }
    }

    double internal_total = 0.0;
    double internal_matched = 0.0;
    for (const EdgeRecord& edge : edges) {
        if (edge.outer_side >= 0) {
            continue;
        }
        internal_total += edge.length;
        internal_matched += std::min(
            edge.length,
            interval_union_length(edge.matches)
        );
    }

    unsigned int reached = 1;
    for (int pass = 0; pass < int(layout.size()); ++pass) {
        for (int piece_id = 0; piece_id < int(layout.size()); ++piece_id) {
            if (reached & (1u << piece_id)) {
                reached |= adjacency[piece_id];
            }
        }
    }

    DetailedQuality quality;
    quality.internal = (
        internal_total > 1.0
        ? internal_matched / internal_total
        : 1.0
    );
    quality.boundary = (
        interval_union_length(boundary_intervals[0])
        + interval_union_length(boundary_intervals[1])
        + interval_union_length(boundary_intervals[2])
        + interval_union_length(boundary_intervals[3])
    ) / std::max(1.0, 2.0 * (width + height - 2));
    double horizontal_length = std::max(1.0, double(width - 1));
    double vertical_length = std::max(1.0, double(height - 1));
    double side_coverage[4] = {
        interval_union_length(boundary_intervals[0]) / horizontal_length,
        interval_union_length(boundary_intervals[1]) / horizontal_length,
        interval_union_length(boundary_intervals[2]) / vertical_length,
        interval_union_length(boundary_intervals[3]) / vertical_length,
    };
    quality.boundary_min = *std::min_element(
        side_coverage,
        side_coverage + 4
    );
    quality.boundary_max_gap = std::max({
        interval_max_gap_ratio(
            boundary_intervals[0],
            horizontal_length
        ),
        interval_max_gap_ratio(
            boundary_intervals[1],
            horizontal_length
        ),
        interval_max_gap_ratio(
            boundary_intervals[2],
            vertical_length
        ),
        interval_max_gap_ratio(
            boundary_intervals[3],
            vertical_length
        ),
    });
    quality.boundary_angle_error = boundary_angle_error;
    quality.connected = (
        reached == (1u << layout.size()) - 1
        ? 1.0
        : 0.0
    );
    return quality;
}

struct SearchResult {
    bool valid = false;
    std::vector<std::vector<Point>> layout;
    double score = 0.0;
    double coverage = 0.0;
    double overlap = 0.0;
    double internal_quality = 0.0;
    double boundary_quality = 0.0;
    double connected = 0.0;
    int width = 0;
    int height = 0;
    std::uint64_t evaluated = 0;
};

static SearchResult search_ratio(
    const std::vector<std::vector<Point>>& polygons,
    double ratio,
    int position_step
) {
    SearchResult result;
    int width = int(std::lround(std::sqrt(6000.0 * ratio)));
    int height = int(std::lround(6000.0 / width));
    int pixel_count = width * height;
    int word_count = (pixel_count + 63) / 64;
    std::vector<std::vector<Candidate>> candidate_sets;
    for (const std::vector<Point>& polygon : polygons) {
        candidate_sets.push_back(
            generate_candidates(
                polygon,
                width,
                height,
                position_step
            )
        );
        if (candidate_sets.back().empty()) {
            return result;
        }
    }

    std::vector<std::vector<std::vector<float>>> contact_cache(
        polygons.size(),
        std::vector<std::vector<float>>(polygons.size())
    );
    for (int first = 0; first < int(polygons.size()); ++first) {
        for (
            int second = first + 1;
            second < int(polygons.size());
            ++second
        ) {
            std::size_t count = (
                candidate_sets[first].size()
                * candidate_sets[second].size()
            );
            if (count <= 1200000) {
                contact_cache[first][second].assign(count, -1.0f);
            }
        }
    }
    auto cached_contact = [&](
        int first_piece,
        int first_candidate,
        int second_piece,
        int second_candidate
    ) {
        if (first_piece > second_piece) {
            std::swap(first_piece, second_piece);
            std::swap(first_candidate, second_candidate);
        }
        std::vector<float>& cache = contact_cache[
            first_piece
        ][second_piece];
        if (cache.empty()) {
            return internal_edge_match(
                candidate_sets[first_piece][first_candidate].polygon,
                candidate_sets[second_piece][second_candidate].polygon
            );
        }
        std::size_t index = (
            std::size_t(first_candidate)
            * candidate_sets[second_piece].size()
            + second_candidate
        );
        if (cache[index] < 0.0f) {
            cache[index] = float(
                internal_edge_match(
                    candidate_sets[first_piece][
                        first_candidate
                    ].polygon,
                    candidate_sets[second_piece][
                        second_candidate
                    ].polygon
                )
            );
        }
        return double(cache[index]);
    };

    std::vector<int> piece_order(polygons.size());
    for (int index = 0; index < int(polygons.size()); ++index) {
        piece_order[index] = index;
    }
    std::sort(
        piece_order.begin(),
        piece_order.end(),
        [&](int first, int second) {
            return (
                candidate_sets[first].size()
                < candidate_sets[second].size()
            );
        }
    );

    State initial;
    initial.union_mask.assign(word_count, 0);
    initial.core_union.assign(word_count, 0);
    initial.choices.assign(polygons.size(), -1);
    std::vector<State> states;
    states.push_back(std::move(initial));

    for (int piece_id : piece_order) {
        auto lower_rank = [](const State& first, const State& second) {
            return first.rank > second.rank;
        };
        std::priority_queue<
            State,
            std::vector<State>,
            decltype(lower_rank)
        > best_states(lower_rank);

        for (const State& state : states) {
            for (
                int candidate_id = 0;
                candidate_id < int(candidate_sets[piece_id].size());
                ++candidate_id
            ) {
                ++result.evaluated;
                const Candidate& candidate = (
                    candidate_sets[piece_id][candidate_id]
                );
                bool geometry_overlap = false;
                for (
                    int old_piece_id = 0;
                    old_piece_id < int(polygons.size());
                    ++old_piece_id
                ) {
                    int old_candidate_id = state.choices[old_piece_id];
                    if (
                        old_candidate_id >= 0
                        && polygons_overlap(
                            candidate.polygon,
                            candidate_sets[old_piece_id][
                                old_candidate_id
                            ].polygon
                        )
                    ) {
                        geometry_overlap = true;
                        break;
                    }
                }
                if (geometry_overlap) {
                    continue;
                }
                int boundary_overlap = intersection_count(
                    state.union_mask,
                    candidate.mask
                );
                int interior_overlap = std::max(
                    intersection_count(
                        state.union_mask,
                        candidate.core
                    ),
                    intersection_count(
                        state.core_union,
                        candidate.mask
                    )
                );
                if (
                    interior_overlap
                    > std::max(6, int(candidate.area * 0.012))
                ) {
                    continue;
                }

                int covered = (
                    state.covered
                    + candidate.area
                    - boundary_overlap
                );
                int overlap = state.overlap + interior_overlap;
                int corners = state.corners | candidate.corners;
                double proximity = state.proximity;
                double contact = state.contact;
                for (
                    int old_piece_id = 0;
                    old_piece_id < int(polygons.size());
                    ++old_piece_id
                ) {
                    int old_candidate_id = state.choices[old_piece_id];
                    if (old_candidate_id >= 0) {
                        contact += cached_contact(
                            piece_id,
                            candidate_id,
                            old_piece_id,
                            old_candidate_id
                        );
                        proximity += vertex_proximity(
                            candidate.polygon,
                            candidate_sets[old_piece_id][
                                old_candidate_id
                            ].polygon
                        );
                    }
                }
                double rank = (
                    covered
                    - overlap * 12.0
                    + __builtin_popcount(unsigned(corners))
                    * pixel_count
                    * 0.18
                    + proximity * 2.5
                    + contact * 35.0
                );
                if (
                    best_states.size() >= 480
                    && rank <= best_states.top().rank
                ) {
                    continue;
                }

                State next;
                next.union_mask.resize(word_count);
                next.core_union.resize(word_count);
                for (int word = 0; word < word_count; ++word) {
                    next.union_mask[word] = (
                        state.union_mask[word]
                        | candidate.mask[word]
                    );
                    next.core_union[word] = (
                        state.core_union[word]
                        | candidate.core[word]
                    );
                }
                next.choices = state.choices;
                next.choices[piece_id] = candidate_id;
                next.covered = covered;
                next.overlap = overlap;
                next.corners = corners;
                next.proximity = proximity;
                next.contact = contact;
                next.rank = rank;
                best_states.push(std::move(next));
                if (best_states.size() > 480) {
                    best_states.pop();
                }
            }
        }
        states.clear();
        states.reserve(best_states.size());
        while (!best_states.empty()) {
            states.push_back(best_states.top());
            best_states.pop();
        }
        if (states.empty()) {
            return result;
        }
    }

    const State* best = nullptr;
    std::vector<std::vector<Point>> best_layout;
    DetailedQuality best_quality;
    double best_score = -std::numeric_limits<double>::infinity();
    for (const State& state : states) {
        if (state.corners != 15 || state.overlap != 0) {
            continue;
        }
        std::vector<std::vector<Point>> layout(polygons.size());
        for (
            int piece_id = 0;
            piece_id < int(polygons.size());
            ++piece_id
        ) {
            layout[piece_id] = candidate_sets[piece_id][
                state.choices[piece_id]
            ].polygon;
        }
        DetailedQuality quality = evaluate_detailed_quality(
            layout,
            width,
            height
        );
        double coverage = double(state.covered) / pixel_count;
        if (
            coverage < 0.82
            || quality.internal < 0.42
            || quality.boundary_min < 0.88
            || quality.boundary_max_gap > 0.12
            || quality.boundary_angle_error > 7.0
            || quality.connected < 0.5
        ) {
            continue;
        }
        double score = (
            coverage * 1.35
            + quality.internal * 0.30
            + quality.boundary * 0.10
            + quality.connected * 0.06
        );
        if (score > best_score) {
            best = &state;
            best_layout = std::move(layout);
            best_quality = quality;
            best_score = score;
        }
    }
    if (best == nullptr) {
        return result;
    }

    result.valid = true;
    result.layout = std::move(best_layout);
    result.coverage = double(best->covered) / pixel_count;
    result.overlap = double(best->overlap) / pixel_count;
    result.internal_quality = best_quality.internal;
    result.boundary_quality = best_quality.boundary;
    result.connected = best_quality.connected;
    result.score = best_score - result.overlap * 2.0;
    result.width = width;
    result.height = height;
    return result;
}

extern "C" int solve_rectangle_cpp(
    const double* input_points,
    const int* point_counts,
    int piece_count,
    double fill_ratio,
    int position_step,
    double* output_points,
    double* output_info
) {
    if (
        input_points == nullptr
        || point_counts == nullptr
        || output_points == nullptr
        || output_info == nullptr
        || piece_count < 2
        || piece_count > 4
    ) {
        return -1;
    }

    std::vector<std::vector<Point>> polygons(piece_count);
    int input_offset = 0;
    double total_area = 0.0;
    for (int piece_id = 0; piece_id < piece_count; ++piece_id) {
        int count = point_counts[piece_id];
        if (count < 3 || count > 5) {
            return -2;
        }
        for (int point_id = 0; point_id < count; ++point_id) {
            polygons[piece_id].push_back({
                input_points[(input_offset + point_id) * 2],
                input_points[(input_offset + point_id) * 2 + 1],
            });
        }
        input_offset += count;
        double area = polygon_area(polygons[piece_id]);
        if (area < 0.0) {
            std::reverse(
                polygons[piece_id].begin(),
                polygons[piece_id].end()
            );
            area = -area;
        }
        total_area += area;
    }
    if (total_area < 100.0) {
        return -3;
    }

    double solve_scale = std::sqrt(
        6000.0 * fill_ratio / total_area
    );
    for (std::vector<Point>& polygon : polygons) {
        for (Point& point : polygon) {
            point.x *= solve_scale;
            point.y *= solve_scale;
        }
    }

    const double ratios[] = {
        10.0 / 6.0,
        1.45,
        1.50,
        1.40,
        1.60,
        1.80,
        2.00,
        1.20,
        2.20,
        1.00,
        2.40,
    };
    int ratio_count = int(sizeof(ratios) / sizeof(ratios[0]));
    std::vector<SearchResult> results(ratio_count);
    std::atomic<int> next_ratio{0};
    auto run_ratios = [&]() {
        while (true) {
            int ratio_id = next_ratio.fetch_add(1);
            if (ratio_id >= ratio_count) {
                return;
            }
            results[ratio_id] = search_ratio(
                polygons,
                ratios[ratio_id],
                position_step
            );
        }
    };
    std::vector<std::thread> workers;
    for (int worker_id = 0; worker_id < 2; ++worker_id) {
        workers.emplace_back(run_ratios);
    }
    for (std::thread& worker : workers) {
        worker.join();
    }

    SearchResult best;
    std::uint64_t evaluated = 0;
    for (SearchResult& current : results) {
        evaluated += current.evaluated;
        if (
            current.valid
            && (!best.valid || current.score > best.score)
        ) {
            best = std::move(current);
        }
    }
    best.evaluated = evaluated;
    if (!best.valid) {
        output_info[7] = double(best.evaluated);
        return 0;
    }

    int output_offset = 0;
    for (int piece_id = 0; piece_id < piece_count; ++piece_id) {
        for (const Point& point : best.layout[piece_id]) {
            output_points[output_offset * 2] = point.x;
            output_points[output_offset * 2 + 1] = point.y;
            ++output_offset;
        }
    }
    output_info[0] = best.score;
    output_info[1] = best.coverage;
    output_info[2] = best.overlap;
    output_info[3] = best.width;
    output_info[4] = best.height;
    output_info[5] = (
        double(std::max(best.width, best.height))
        / std::max(1, std::min(best.width, best.height))
    );
    output_info[6] = solve_scale;
    output_info[7] = double(best.evaluated);
    output_info[8] = best.internal_quality;
    output_info[9] = best.boundary_quality;
    output_info[10] = best.connected;
    return 1;
}
