#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <queue>
#include <string>
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
    unsigned int adjacency = 0;
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

static Point line_intersection(
    const Point& first_start,
    const Point& first_end,
    const Point& second_start,
    const Point& second_end
) {
    double first_x = first_end.x - first_start.x;
    double first_y = first_end.y - first_start.y;
    double second_x = second_end.x - second_start.x;
    double second_y = second_end.y - second_start.y;
    double denominator = first_x * second_y - first_y * second_x;
    if (std::abs(denominator) < 1e-9) {
        return first_end;
    }
    double offset_x = second_start.x - first_start.x;
    double offset_y = second_start.y - first_start.y;
    double amount = (
        offset_x * second_y - offset_y * second_x
    ) / denominator;
    return {
        first_start.x + first_x * amount,
        first_start.y + first_y * amount,
    };
}

static double convex_overlap_area(
    const std::vector<Point>& first,
    const std::vector<Point>& second
) {
    std::vector<Point> clipped = first;
    for (std::size_t edge_id = 0; edge_id < second.size(); ++edge_id) {
        if (clipped.empty()) {
            return 0.0;
        }
        const Point& clip_start = second[edge_id];
        const Point& clip_end = second[(edge_id + 1) % second.size()];
        std::vector<Point> input = std::move(clipped);
        clipped.clear();
        Point previous = input.back();
        bool previous_inside = (
            cross(clip_start, clip_end, previous) >= -1e-7
        );
        for (const Point& current : input) {
            bool current_inside = (
                cross(clip_start, clip_end, current) >= -1e-7
            );
            if (current_inside != previous_inside) {
                clipped.push_back(
                    line_intersection(
                        previous,
                        current,
                        clip_start,
                        clip_end
                    )
                );
            }
            if (current_inside) {
                clipped.push_back(current);
            }
            previous = current;
            previous_inside = current_inside;
        }
    }
    return std::abs(polygon_area(clipped));
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

static double edge_contact_length(
    const std::vector<Point>& first,
    const std::vector<Point>& second
) {
    double total = 0.0;
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
            double second_first = (
                (second_start.x - first_start.x) * unit_x
                + (second_start.y - first_start.y) * unit_y
            );
            double second_last = (
                (second_end.x - first_start.x) * unit_x
                + (second_end.y - first_start.y) * unit_y
            );
            double overlap = (
                std::min(
                    first_length,
                    std::max(second_first, second_last)
                )
                - std::max(
                    0.0,
                    std::min(second_first, second_last)
                )
            );
            if (overlap > 4.0) {
                total += overlap * (1.0 - line_offset / 3.5);
            }
        }
    }
    return total;
}

static bool adjacency_is_connected(
    unsigned int adjacency,
    int piece_count
) {
    unsigned int reached = 1;
    for (int pass = 0; pass < piece_count; ++pass) {
        for (int first = 0; first < piece_count; ++first) {
            if ((reached & (1u << first)) == 0) {
                continue;
            }
            for (int second = 0; second < piece_count; ++second) {
                if (
                    adjacency & (1u << (first * 4 + second))
                ) {
                    reached |= 1u << second;
                }
            }
        }
    }
    return reached == (1u << piece_count) - 1;
}

static Point polygon_center(const std::vector<Point>& polygon) {
    Point center{0.0, 0.0};
    for (const Point& point : polygon) {
        center.x += point.x;
        center.y += point.y;
    }
    center.x /= polygon.size();
    center.y /= polygon.size();
    return center;
}

static std::vector<Point> align_matching_segment(
    const std::vector<Point>& polygon,
    int edge_id,
    double source_offset,
    double shared_length,
    const Point& target_start,
    const Point& target_end
) {
    const Point& source_start = polygon[edge_id];
    const Point& source_end = polygon[(edge_id + 1) % polygon.size()];
    double source_length = distance(source_start, source_end);
    double source_unit_x = (
        source_end.x - source_start.x
    ) / source_length;
    double source_unit_y = (
        source_end.y - source_start.y
    ) / source_length;
    Point segment_start{
        source_start.x + source_unit_x * source_offset,
        source_start.y + source_unit_y * source_offset,
    };
    Point segment_end{
        segment_start.x + source_unit_x * shared_length,
        segment_start.y + source_unit_y * shared_length,
    };
    double source_angle = std::atan2(
        segment_end.y - segment_start.y,
        segment_end.x - segment_start.x
    );
    double target_angle = std::atan2(
        target_start.y - target_end.y,
        target_start.x - target_end.x
    );
    double angle = target_angle - source_angle;
    double cosine = std::cos(angle);
    double sine = std::sin(angle);
    Point source_middle{
        (segment_start.x + segment_end.x) * 0.5,
        (segment_start.y + segment_end.y) * 0.5,
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

static std::vector<Point> convex_hull(std::vector<Point> points) {
    std::sort(
        points.begin(),
        points.end(),
        [](const Point& first, const Point& second) {
            return (
                first.x < second.x
                || (
                    std::abs(first.x - second.x) < 1e-9
                    && first.y < second.y
                )
            );
        }
    );
    points.erase(
        std::unique(
            points.begin(),
            points.end(),
            [](const Point& first, const Point& second) {
                return (
                    std::abs(first.x - second.x) < 1e-9
                    && std::abs(first.y - second.y) < 1e-9
                );
            }
        ),
        points.end()
    );
    if (points.size() <= 2) {
        return points;
    }
    std::vector<Point> hull(points.size() * 2);
    int count = 0;
    for (const Point& point : points) {
        while (
            count >= 2
            && cross(hull[count - 2], hull[count - 1], point) <= 0.0
        ) {
            --count;
        }
        hull[count++] = point;
    }
    int lower_count = count + 1;
    for (int index = int(points.size()) - 2; index >= 0; --index) {
        const Point& point = points[index];
        while (
            count >= lower_count
            && cross(hull[count - 2], hull[count - 1], point) <= 0.0
        ) {
            --count;
        }
        hull[count++] = point;
    }
    hull.resize(count - 1);
    return hull;
}

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
        if (intervals[index].first <= end + 1.0) {
            end = std::max(end, intervals[index].second);
        } else {
            total += end - start;
            start = intervals[index].first;
            end = intervals[index].second;
        }
    }
    return total + end - start;
}

struct AssemblyResult {
    bool valid = false;
    std::vector<std::vector<Point>> layout;
    double score = 0.0;
    double coverage = 0.0;
    double overlap = 0.0;
    double edge_match = 0.0;
    int width = 0;
    int height = 0;
    std::uint64_t evaluated = 0;
};

static AssemblyResult evaluate_assembly(
    const std::vector<std::vector<Point>>& layout,
    double match_error
) {
    AssemblyResult result;
    std::vector<Point> all_points;
    double piece_area = 0.0;
    for (const std::vector<Point>& polygon : layout) {
        all_points.insert(
            all_points.end(),
            polygon.begin(),
            polygon.end()
        );
        piece_area += std::abs(polygon_area(polygon));
    }
    std::vector<Point> hull = convex_hull(all_points);
    if (hull.size() < 3) {
        return result;
    }

    double best_area = std::numeric_limits<double>::infinity();
    double best_angle = 0.0;
    double best_minimum_x = 0.0;
    double best_minimum_y = 0.0;
    double best_width = 0.0;
    double best_height = 0.0;
    for (std::size_t edge_id = 0; edge_id < hull.size(); ++edge_id) {
        const Point& first = hull[edge_id];
        const Point& second = hull[(edge_id + 1) % hull.size()];
        double angle = -std::atan2(
            second.y - first.y,
            second.x - first.x
        );
        double cosine = std::cos(angle);
        double sine = std::sin(angle);
        double minimum_x = std::numeric_limits<double>::infinity();
        double minimum_y = std::numeric_limits<double>::infinity();
        double maximum_x = -minimum_x;
        double maximum_y = -minimum_y;
        for (const Point& point : all_points) {
            double x = point.x * cosine - point.y * sine;
            double y = point.x * sine + point.y * cosine;
            minimum_x = std::min(minimum_x, x);
            minimum_y = std::min(minimum_y, y);
            maximum_x = std::max(maximum_x, x);
            maximum_y = std::max(maximum_y, y);
        }
        double width = maximum_x - minimum_x;
        double height = maximum_y - minimum_y;
        double area = width * height;
        if (area < best_area) {
            best_area = area;
            best_angle = angle;
            best_minimum_x = minimum_x;
            best_minimum_y = minimum_y;
            best_width = width;
            best_height = height;
        }
    }
    if (best_area < 1.0 || std::min(best_width, best_height) < 1.0) {
        return result;
    }

    double cosine = std::cos(best_angle);
    double sine = std::sin(best_angle);
    std::vector<std::vector<Point>> normalized(layout.size());
    for (std::size_t piece_id = 0; piece_id < layout.size(); ++piece_id) {
        for (const Point& point : layout[piece_id]) {
            normalized[piece_id].push_back({
                point.x * cosine - point.y * sine - best_minimum_x,
                point.x * sine + point.y * cosine - best_minimum_y,
            });
        }
    }

    double diagonal = std::hypot(best_width, best_height);
    double tolerance = std::max(3.0, diagonal * 0.05);
    int corner_count = 0;
    const Point corners[4] = {
        {0.0, 0.0},
        {best_width, 0.0},
        {best_width, best_height},
        {0.0, best_height},
    };
    for (const Point& corner : corners) {
        double nearest = std::numeric_limits<double>::infinity();
        for (const std::vector<Point>& polygon : normalized) {
            for (const Point& point : polygon) {
                nearest = std::min(nearest, distance(point, corner));
            }
        }
        if (nearest <= tolerance) {
            ++corner_count;
        }
    }

    std::array<std::vector<std::pair<double, double>>, 4> intervals;
    int outer_piece_count = 0;
    for (const std::vector<Point>& polygon : normalized) {
        bool has_outer = false;
        for (std::size_t edge_id = 0; edge_id < polygon.size(); ++edge_id) {
            const Point& start = polygon[edge_id];
            const Point& end = polygon[(edge_id + 1) % polygon.size()];
            if (std::max(std::abs(start.y), std::abs(end.y)) <= tolerance) {
                intervals[0].push_back({
                    std::min(start.x, end.x),
                    std::max(start.x, end.x),
                });
                has_outer = true;
            } else if (
                std::max(
                    std::abs(start.y - best_height),
                    std::abs(end.y - best_height)
                ) <= tolerance
            ) {
                intervals[1].push_back({
                    std::min(start.x, end.x),
                    std::max(start.x, end.x),
                });
                has_outer = true;
            } else if (
                std::max(std::abs(start.x), std::abs(end.x)) <= tolerance
            ) {
                intervals[2].push_back({
                    std::min(start.y, end.y),
                    std::max(start.y, end.y),
                });
                has_outer = true;
            } else if (
                std::max(
                    std::abs(start.x - best_width),
                    std::abs(end.x - best_width)
                ) <= tolerance
            ) {
                intervals[3].push_back({
                    std::min(start.y, end.y),
                    std::max(start.y, end.y),
                });
                has_outer = true;
            }
        }
        if (has_outer) {
            ++outer_piece_count;
        }
    }
    double boundary_coverage = (
        interval_union_length(intervals[0])
        + interval_union_length(intervals[1])
        + interval_union_length(intervals[2])
        + interval_union_length(intervals[3])
    ) / (2.0 * (best_width + best_height));
    double overlap_area = 0.0;
    for (std::size_t first_id = 0; first_id < layout.size(); ++first_id) {
        for (
            std::size_t second_id = first_id + 1;
            second_id < layout.size();
            ++second_id
        ) {
            overlap_area += convex_overlap_area(
                layout[first_id],
                layout[second_id]
            );
        }
    }
    double overlap = overlap_area / best_area;
    double coverage = (piece_area - overlap_area) / best_area;
    double aspect = (
        std::max(best_width, best_height)
        / std::min(best_width, best_height)
    );
    double edge_match = std::max(
        0.0,
        1.0 - match_error / std::max(1.0, layout.size() - 1.0)
    );
    result.valid = (
        coverage >= 0.84
        && coverage <= 1.02
        && overlap <= 0.025
        && corner_count == 4
        && outer_piece_count == int(layout.size())
        && aspect <= 2.45
    );
    result.layout = std::move(normalized);
    result.coverage = coverage;
    result.overlap = overlap;
    result.edge_match = edge_match;
    result.score = (
        coverage
        + boundary_coverage * 0.20
        + edge_match * 0.12
        + corner_count * 0.025
        + outer_piece_count * 0.015
        - overlap * 5.0
    );
    result.width = int(std::lround(best_width));
    result.height = int(std::lround(best_height));
    return result;
}

struct AssemblyBranch {
    int source_id;
    std::vector<Point> polygon;
    double error;
};

static void search_assembly_recursive(
    const std::vector<std::vector<Point>>& polygons,
    std::vector<std::vector<Point>>& placed,
    std::vector<bool>& is_placed,
    int placed_count,
    double match_error,
    std::uint64_t& evaluated,
    AssemblyResult& best
) {
    if (evaluated >= 1500000) {
        return;
    }
    ++evaluated;
    if (placed_count == int(polygons.size())) {
        AssemblyResult current = evaluate_assembly(placed, match_error);
        if (current.valid && (!best.valid || current.score > best.score)) {
            best = std::move(current);
        }
        return;
    }

    std::vector<AssemblyBranch> branches;
    std::unordered_set<std::string> generated;
    for (int target_id = 0; target_id < int(polygons.size()); ++target_id) {
        if (!is_placed[target_id]) {
            continue;
        }
        const std::vector<Point>& target = placed[target_id];
        Point target_center = polygon_center(target);
        for (int target_edge = 0; target_edge < int(target.size()); ++target_edge) {
            const Point& target_start = target[target_edge];
            const Point& target_end = target[
                (target_edge + 1) % target.size()
            ];
            double target_length = distance(target_start, target_end);
            for (int source_id = 0; source_id < int(polygons.size()); ++source_id) {
                if (is_placed[source_id]) {
                    continue;
                }
                const std::vector<Point>& source = polygons[source_id];
                for (
                    int source_edge = 0;
                    source_edge < int(source.size());
                    ++source_edge
                ) {
                    double source_length = distance(
                        source[source_edge],
                        source[(source_edge + 1) % source.size()]
                    );
                    double relative_error = (
                        std::abs(target_length - source_length)
                        / std::max(target_length, source_length)
                    );
                    if (relative_error > 0.35) {
                        continue;
                    }
                    double shared = std::min(
                        target_length,
                        source_length
                    );
                    double target_maximum = target_length - shared;
                    double source_maximum = source_length - shared;
                    std::array<double, 2> target_offsets{
                        0.0,
                        target_maximum,
                    };
                    std::array<double, 2> source_offsets{
                        0.0,
                        source_maximum,
                    };
                    double target_unit_x = (
                        target_end.x - target_start.x
                    ) / target_length;
                    double target_unit_y = (
                        target_end.y - target_start.y
                    ) / target_length;
                    for (int target_position = 0; target_position < 2; ++target_position) {
                        if (
                            target_position == 1
                            && target_maximum < 0.25
                        ) {
                            continue;
                        }
                        Point segment_start{
                            target_start.x
                            + target_unit_x
                            * target_offsets[target_position],
                            target_start.y
                            + target_unit_y
                            * target_offsets[target_position],
                        };
                        Point segment_end{
                            segment_start.x + target_unit_x * shared,
                            segment_start.y + target_unit_y * shared,
                        };
                        for (int source_position = 0; source_position < 2; ++source_position) {
                            if (
                                source_position == 1
                                && source_maximum < 0.25
                            ) {
                                continue;
                            }
                            std::vector<Point> transformed = (
                                align_matching_segment(
                                    source,
                                    source_edge,
                                    source_offsets[source_position],
                                    shared,
                                    segment_start,
                                    segment_end
                                )
                            );
                            Point source_center = polygon_center(
                                transformed
                            );
                            if (
                                cross(
                                    segment_start,
                                    segment_end,
                                    target_center
                                )
                                * cross(
                                    segment_start,
                                    segment_end,
                                    source_center
                                ) >= 0.0
                            ) {
                                continue;
                            }
                            bool overlap = false;
                            for (
                                int old_id = 0;
                                old_id < int(polygons.size());
                                ++old_id
                            ) {
                                if (
                                    is_placed[old_id]
                                    && convex_overlap_area(
                                        transformed,
                                        placed[old_id]
                                    ) > std::min(
                                        std::abs(
                                            polygon_area(transformed)
                                        ),
                                        std::abs(
                                            polygon_area(placed[old_id])
                                        )
                                    ) * 0.025
                                ) {
                                    overlap = true;
                                    break;
                                }
                            }
                            if (overlap) {
                                continue;
                            }
                            Point center = polygon_center(transformed);
                            std::string key = (
                                std::to_string(source_id)
                                + ":"
                                + std::to_string(
                                    int(std::lround(center.x * 2.0))
                                )
                                + ":"
                                + std::to_string(
                                    int(std::lround(center.y * 2.0))
                                )
                            );
                            if (!generated.insert(key).second) {
                                continue;
                            }
                            branches.push_back({
                                source_id,
                                std::move(transformed),
                                relative_error,
                            });
                        }
                    }
                }
            }
        }
    }
    std::sort(
        branches.begin(),
        branches.end(),
        [](const AssemblyBranch& first, const AssemblyBranch& second) {
            return first.error < second.error;
        }
    );
    if (branches.size() > 800) {
        branches.resize(800);
    }
    for (AssemblyBranch& branch : branches) {
        placed[branch.source_id] = std::move(branch.polygon);
        is_placed[branch.source_id] = true;
        search_assembly_recursive(
            polygons,
            placed,
            is_placed,
            placed_count + 1,
            match_error + branch.error,
            evaluated,
            best
        );
        is_placed[branch.source_id] = false;
    }
}

static AssemblyResult search_edge_assembly(
    const std::vector<std::vector<Point>>& polygons
) {
    AssemblyResult best;
    std::uint64_t evaluated = 0;
    for (int seed_id = 0; seed_id < int(polygons.size()); ++seed_id) {
        std::vector<std::vector<Point>> placed(polygons.size());
        std::vector<bool> is_placed(polygons.size(), false);
        placed[seed_id] = polygons[seed_id];
        is_placed[seed_id] = true;
        search_assembly_recursive(
            polygons,
            placed,
            is_placed,
            1,
            0.0,
            evaluated,
            best
        );
    }
    best.evaluated = evaluated;
    return best;
}

struct SearchResult {
    bool valid = false;
    std::vector<std::vector<Point>> layout;
    double score = 0.0;
    double coverage = 0.0;
    double overlap = 0.0;
    double edge_match = 0.0;
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
                unsigned int adjacency = state.adjacency;
                for (
                    int old_piece_id = 0;
                    old_piece_id < int(polygons.size());
                    ++old_piece_id
                ) {
                    int old_candidate_id = state.choices[old_piece_id];
                    if (old_candidate_id >= 0) {
                        double pair_contact = edge_contact_length(
                            candidate.polygon,
                            candidate_sets[old_piece_id][
                                old_candidate_id
                            ].polygon
                        );
                        contact += pair_contact;
                        if (pair_contact >= 6.0) {
                            adjacency |= (
                                1u << (piece_id * 4 + old_piece_id)
                            );
                            adjacency |= (
                                1u << (old_piece_id * 4 + piece_id)
                            );
                        }
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
                    + contact * 40.0
                    + proximity * 0.15
                );
                if (
                    best_states.size() >= 240
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
                next.adjacency = adjacency;
                next.proximity = proximity;
                next.contact = contact;
                next.rank = rank;
                best_states.push(std::move(next));
                if (best_states.size() > 240) {
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
    for (const State& state : states) {
        if (
            state.corners == 15
            && state.overlap == 0
            && adjacency_is_connected(
                state.adjacency,
                int(polygons.size())
            )
            && (best == nullptr || state.rank > best->rank)
        ) {
            best = &state;
        }
    }
    if (best == nullptr) {
        return result;
    }

    result.valid = true;
    result.layout.resize(polygons.size());
    for (int piece_id = 0; piece_id < int(polygons.size()); ++piece_id) {
        result.layout[piece_id] = candidate_sets[piece_id][
            best->choices[piece_id]
        ].polygon;
    }
    result.coverage = double(best->covered) / pixel_count;
    result.overlap = double(best->overlap) / pixel_count;
    result.edge_match = (
        best->contact
        / (std::sqrt(double(pixel_count)) * (polygons.size() - 1))
    );
    result.score = (
        result.coverage
        - result.overlap * 2.0
        + std::min(1.0, result.edge_match) * 0.25
    );
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

    if (fill_ratio >= 0.97) {
        AssemblyResult assembly = search_edge_assembly(polygons);
        if (assembly.valid) {
            int output_offset = 0;
            for (
                const std::vector<Point>& polygon : assembly.layout
            ) {
                for (const Point& point : polygon) {
                    output_points[output_offset * 2] = point.x;
                    output_points[output_offset * 2 + 1] = point.y;
                    ++output_offset;
                }
            }
            output_info[0] = assembly.score;
            output_info[1] = assembly.coverage;
            output_info[2] = assembly.overlap;
            output_info[3] = assembly.width;
            output_info[4] = assembly.height;
            output_info[5] = (
                double(std::max(assembly.width, assembly.height))
                / std::max(1, std::min(assembly.width, assembly.height))
            );
            output_info[6] = 1.0;
            output_info[7] = double(assembly.evaluated);
            output_info[8] = assembly.edge_match;
            output_info[9] = 1.0;
            return 1;
        }
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
    SearchResult best;
    for (double ratio : ratios) {
        SearchResult current = search_ratio(
            polygons,
            ratio,
            position_step
        );
        best.evaluated += current.evaluated;
        if (
            current.valid
            && (!best.valid || current.score > best.score)
        ) {
            std::uint64_t evaluated = best.evaluated;
            best = std::move(current);
            best.evaluated = evaluated;
        }
    }
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
    output_info[8] = best.edge_match;
    output_info[9] = 0.0;
    return 1;
}
