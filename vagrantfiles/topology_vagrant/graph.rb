module GraphObj
  class Nodes
    attr_accessor :name, :mem, :cpus, :box, :xrsshport, :xrcnslport, :xrauxport, :node_link_name, :node_link_type, :node_intf_ip
    def initialize(node_specs={})
      node_specs.each { |k,v| instance_variable_set("@#{k}", v) }
      @node_link_name = {}
      @node_link_type = {}
      @node_intf_ip = {}
    end
  end

# Read yaml topology definitions to create a graph object

  def yml_to_obj
    graph = YAML.load_file(File.join(__dir__,'topology.yml'))
    node_specs = graph["nodes"]
    edges = graph["edges"]

    nodes = {}
    node_specs.each do |node_spec|
      nodes["#{node_spec["name"]}"] =   Nodes.new(node_spec)
    end

    edges.each do |edge|
      if edge["type"] == "private_internal"
         nodes["#{edge["headnode"]["name"]}"].node_link_name["#{edge["headnode"]["interface"]}"] = edge["name"]
         nodes["#{edge["headnode"]["name"]}"].node_link_type["#{edge["headnode"]["interface"]}"] = edge["type"]

         nodes["#{edge["tailnode"]["name"]}"].node_link_name["#{edge["tailnode"]["interface"]}"] = edge["name"]
         nodes["#{edge["tailnode"]["name"]}"].node_link_type["#{edge["tailnode"]["interface"]}"] = edge["type"]

      end

      if edge["type"] == "private_shared"
         edge["nodes"].each do |shared_node|
             nodes["#{shared_node["name"]}"].node_link_name["#{shared_node["interface"]}"] = edge["name"]
             nodes["#{shared_node["name"]}"].node_link_type["#{shared_node["interface"]}"] = edge["type"]
             nodes["#{shared_node["name"]}"].node_intf_ip["#{shared_node["interface"]}"] = shared_node["ip"]
         end
      end
    end

    return nodes
  end
end
